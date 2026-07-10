"""Query-count regression guard for the two normalized line readers
(app/reports/vat_lines.py, app/reports/wht_lines.py).

Both readers iterate posted document headers, then walk each header's line
collection (`SalesInvoice.line_items`, `AccountsPayable.line_items`,
`CashReceiptVoucher.revenue_lines`, `CashDisbursementVoucher.expense_lines`).
Those relationships are `lazy='select'` on the model (and must STAY that way --
other call sites depend on the default), so absent a per-query eager-load
option each header triggers one extra SELECT for its lines: N headers -> N+1
statements, and `wht_lines()` additionally touches `line.withholding_tax` per
line.

This test proves the fix with SQL statement counts, not assertions about
implementation: it counts every statement SQLAlchemy sends to the DB-API via
`before_cursor_execute` around a single `vat_lines(...)` / `wht_lines(...)`
call, for N headers and then N+1 headers, and asserts the count does NOT
grow -- i.e. the query plan is O(1) in the number of matching headers, not
O(N). Before the fix (plain lazy='select', no query-level eager load) this
test fails because the 6-header run emits one more SELECT than the 5-header
run. After eager-loading with `selectinload` (see report for why
`selectinload` over `joinedload` here), both runs emit the same fixed number
of statements.
"""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app import db
from app.reports.vat_lines import vat_lines, VatLine
from app.reports.wht_lines import wht_lines, WhtLine


class _QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1


@contextmanager
def count_queries():
    """Count every SQL statement sent to the DB-API during the `with` block."""
    counter = _QueryCounter()
    engine = db.session.get_bind()
    event.listen(engine, 'before_cursor_execute', counter)
    try:
        yield counter
    finally:
        event.remove(engine, 'before_cursor_execute', counter)


def _make_ap_bills(session, branch, vendor, account, n, wt=None, lines_per_doc=2,
                    start=0):
    """N posted AccountsPayable bills, each with `lines_per_doc` lines (so the
    header COUNT and the LINE count both vary -- proves the fix folds all
    lines of all headers into one statement, not one query per line either).
    `start` offsets the generated ap_number so a second call in the same test
    (adding one more header) doesn't collide with the first batch's unique
    ap_number."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    bills = []
    for i in range(start, start + n):
        bill = AccountsPayable(
            branch_id=branch.id,
            ap_number=f'AP-QC-{i:04d}',
            ap_date=date(2026, 2, 15),
            due_date=date(2026, 3, 17),
            payee_type='vendor', payee_id=vendor.id,
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            vendor_tin=vendor.tin,
            status='posted',
        )
        for j in range(lines_per_doc):
            item = AccountsPayableItem(
                line_number=j + 1, description=f'Line {j + 1}',
                amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
                vat_category='V12SV', vat_nature='domestic_services',
                line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
                wt_id=(wt.id if wt else None),
                wt_rate=(wt.rate if wt else None),
                wt_amount=(Decimal('100.00') if wt else None),
                account_id=account.id,
            )
            bill.line_items.append(item)
        bills.append(bill)
    session.add_all(bills)
    session.commit()
    return bills


class TestVatLinesQueryCount:
    """side='purchases' touches two header collections: AccountsPayable
    (populated) and CashDisbursementVoucher (empty in this test). Expected,
    fixed statement count with the fix applied:
      1 SELECT AccountsPayable headers
    + 1 SELECT (selectin) AccountsPayable.line_items for those headers
    + 1 SELECT CashDisbursementVoucher headers (0 rows match -> no follow-up
        selectin statement is issued for an empty parent set)
    = 3, regardless of how many AP headers/lines matched.
    """

    def test_query_count_does_not_grow_with_header_count(
            self, db_session, main_branch, revenue_account, vl_vendor):
        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account, n=5)

        with count_queries() as counter_5:
            rows_5 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')

        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account,
                       n=1, lines_per_doc=2, start=5)
        with count_queries() as counter_6:
            rows_6 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')

        assert len(rows_5) == 10   # 5 headers x 2 lines
        assert len(rows_6) == 12   # 6 headers x 2 lines
        assert counter_5.count == counter_6.count, (
            f'{counter_5.count} queries for 5 headers vs '
            f'{counter_6.count} queries for 6 headers -- statement count '
            'must be independent of header count')
        assert counter_5.count <= 3, counter_5.count

    def test_rows_are_plain_namedtuples_not_orm_objects(
            self, db_session, main_branch, revenue_account, vl_vendor):
        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account, n=2)
        rows = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')
        assert rows
        for row in rows:
            assert type(row) is VatLine
            assert not hasattr(row, '__mapper__')


def _make_cdv_vouchers(session, branch, vendor, cash_account, account, n, wt=None,
                        start=0):
    from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
    cdvs = []
    for i in range(start, start + n):
        cdv = CashDisbursementVoucher(
            branch_id=branch.id,
            cdv_number=f'CDV-QC-{i:04d}',
            cdv_date=date(2026, 2, 15),
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            vendor_tin=vendor.tin,
            cash_account_id=cash_account.id,
            status='posted',
        )
        for j in range(2):
            line = CDVExpenseLine(
                line_number=j + 1, description=f'Line {j + 1}',
                amount=Decimal('5600.00'), vat_rate=Decimal('12.00'),
                vat_category='V12SV', vat_nature='domestic_services',
                line_total=Decimal('5600.00'), vat_amount=Decimal('600.00'),
                wt_id=(wt.id if wt else None),
                wt_rate=(wt.rate if wt else None),
                wt_amount=(Decimal('100.00') if wt else None),
                account_id=account.id,
            )
            cdv.expense_lines.append(line)
        cdvs.append(cdv)
    session.add_all(cdvs)
    session.commit()
    return cdvs


class TestWhtLinesQueryCount:
    """side='payor' touches AccountsPayable (populated, WHT set on every line)
    and CashDisbursementVoucher (empty). `wht_lines()` additionally reads
    `line.withholding_tax` per line -- eager-loaded via a nested `joinedload`
    inside the same selectin statement, so it adds NO extra round trip.
    Expected, fixed statement count:
      1 SELECT AccountsPayable headers
    + 1 SELECT (selectin, joined to withholding_tax) AccountsPayable.line_items
    + 1 SELECT CashDisbursementVoucher headers (0 rows -> no follow-up)
    = 3, regardless of how many AP headers/lines matched.
    """

    def test_query_count_does_not_grow_with_header_count(
            self, db_session, main_branch, revenue_account, vl_vendor, vl_wht_expanded):
        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account,
                       n=5, wt=vl_wht_expanded)

        with count_queries() as counter_5:
            rows_5 = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')

        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account,
                       n=1, wt=vl_wht_expanded, lines_per_doc=2, start=5)

        with count_queries() as counter_6:
            rows_6 = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')

        assert len(rows_5) == 10   # 5 headers x 2 lines, all carry wt_id
        assert len(rows_6) == 12   # 6 headers x 2 lines
        assert counter_5.count == counter_6.count, (
            f'{counter_5.count} queries for 5 headers vs '
            f'{counter_6.count} queries for 6 headers -- statement count '
            'must be independent of header count')
        assert counter_5.count <= 3, counter_5.count

    def test_rows_are_plain_namedtuples_not_orm_objects(
            self, db_session, main_branch, revenue_account, vl_vendor, vl_wht_expanded):
        _make_ap_bills(db_session, main_branch, vl_vendor, revenue_account,
                       n=2, wt=vl_wht_expanded)
        rows = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')
        assert rows
        for row in rows:
            assert type(row) is WhtLine
            assert not hasattr(row, '__mapper__')


def _make_crv_vouchers(session, branch, customer, cash_account, account, n, start=0):
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    crvs = []
    for i in range(start, start + n):
        crv = CashReceiptVoucher(
            branch_id=branch.id,
            crv_number=f'CRV-QC-{i:04d}',
            crv_date=date(2026, 2, 15),
            customer_id=customer.id,
            customer_name=customer.name,
            customer_tin=customer.tin,
            cash_account_id=cash_account.id,
            status='posted',
        )
        for j in range(2):
            line = CRVRevenueLine(
                line_number=j + 1, description=f'Line {j + 1}',
                amount=Decimal('11200.00'), vat_rate=Decimal('12.00'),
                vat_category='V12', vat_nature='regular',
                line_total=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
                account_id=account.id,
            )
            crv.revenue_lines.append(line)
        crvs.append(crv)
    session.add_all(crvs)
    session.commit()
    return crvs


class TestVatLinesQueryCountWithCrv:
    """Review finding 2 follow-up: `_sales()` now adds `joinedload
    (CashReceiptVoucher.customer)` to source `partner_address`, alongside the
    existing `selectinload(CashReceiptVoucher.revenue_lines)`. A joinedload on
    a many-to-one relationship joins into the SAME header SELECT -- it must
    not add a new statement. Populate the CRV side (SalesInvoice stays empty)
    to prove the sales path is still O(1). Expected, fixed statement count:
      1 SELECT SalesInvoice headers (0 rows -> no follow-up)
    + 1 SELECT (JOIN customers) CashReceiptVoucher headers
    + 1 SELECT (selectin) CashReceiptVoucher.revenue_lines
    = 3, regardless of how many CRV headers/lines matched.
    """

    def test_crv_side_is_also_bounded(
            self, db_session, main_branch, cash_account, revenue_account, vl_customer):
        _make_crv_vouchers(db_session, main_branch, vl_customer, cash_account,
                           revenue_account, n=5)

        with count_queries() as counter_5:
            rows_5 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')

        _make_crv_vouchers(db_session, main_branch, vl_customer, cash_account,
                           revenue_account, n=1, start=5)

        with count_queries() as counter_6:
            rows_6 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'sales')

        assert len(rows_5) == 10
        assert len(rows_6) == 12
        assert counter_5.count == counter_6.count, (
            f'{counter_5.count} queries for 5 CRV headers vs '
            f'{counter_6.count} queries for 6 CRV headers')
        assert counter_5.count <= 3, counter_5.count


class TestVatLinesQueryCountWithCdv:
    """Mirror of the CRV test above for the purchases side: `_purchases()`
    adds `joinedload(CashDisbursementVoucher.vendor)`. Populate the CDV side
    (AccountsPayable stays empty). Expected, fixed statement count:
      1 SELECT AccountsPayable headers (0 rows -> no follow-up)
    + 1 SELECT (JOIN vendors) CashDisbursementVoucher headers
    + 1 SELECT (selectin) CashDisbursementVoucher.expense_lines
    = 3, regardless of how many CDV headers/lines matched.
    """

    def test_cdv_side_is_also_bounded(
            self, db_session, main_branch, cash_account, revenue_account, vl_vendor):
        _make_cdv_vouchers(db_session, main_branch, vl_vendor, cash_account,
                           revenue_account, n=5)

        with count_queries() as counter_5:
            rows_5 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')

        _make_cdv_vouchers(db_session, main_branch, vl_vendor, cash_account,
                           revenue_account, n=1, start=5)

        with count_queries() as counter_6:
            rows_6 = vat_lines(date(2026, 1, 1), date(2026, 3, 31), 'purchases')

        assert len(rows_5) == 10
        assert len(rows_6) == 12
        assert counter_5.count == counter_6.count, (
            f'{counter_5.count} queries for 5 CDV headers vs '
            f'{counter_6.count} queries for 6 CDV headers')
        assert counter_5.count <= 3, counter_5.count


class TestWhtLinesQueryCountWithCdv:
    """Sanity check the CDV side of `wht_lines(side='payor')` is ALSO eager
    loaded (not just AP): mirror the AP-only test above but populate CDV
    instead, and leave AP empty."""

    def test_cdv_side_is_also_bounded(
            self, db_session, main_branch, cash_account, revenue_account,
            vl_vendor, vl_wht_expanded):
        _make_cdv_vouchers(db_session, main_branch, vl_vendor, cash_account,
                           revenue_account, n=5, wt=vl_wht_expanded)

        with count_queries() as counter_5:
            rows_5 = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')

        _make_cdv_vouchers(db_session, main_branch, vl_vendor, cash_account,
                           revenue_account, n=1, wt=vl_wht_expanded, start=5)

        with count_queries() as counter_6:
            rows_6 = wht_lines(date(2026, 1, 1), date(2026, 3, 31), 'payor')

        assert len(rows_5) == 10
        assert len(rows_6) == 12
        assert counter_5.count == counter_6.count, (
            f'{counter_5.count} queries for 5 CDV headers vs '
            f'{counter_6.count} queries for 6 CDV headers')
        assert counter_5.count <= 3, counter_5.count
