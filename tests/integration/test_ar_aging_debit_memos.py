"""Point-in-time settlement lookup for debit memos.

Mirrors `_ar_settled_as_of` (views.py:162) exactly -- same posted-status
filter, same `<= as_of_date` rule, same empty-input short-circuit, same
Decimal conversion -- but keyed on `CRVArLine.sales_memo_id` instead of
`CRVArLine.invoice_id`, because a memo-settling CRV line sets
`sales_memo_id` and leaves `invoice_id` NULL (exactly one of the two is
set, parser-enforced). Widening the existing invoice-keyed filter cannot
reach these rows, so this is a parallel function, not a wider filter.

Settlement here is DERIVED from posted CRVs as of the date -- never read
from `memo.balance` -- for the same reason `03fed0d8` stopped reading the
live SalesInvoice.balance: that is what makes the aging reports true
point-in-time reports rather than a snapshot of today's live state.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from app.reports.views import (
    _memo_settled_as_of, _ar_settled_as_of, _memo_derived_due_date,
    _build_ar_aging_data,
)

pytestmark = [pytest.mark.integration]

AS_OF = date(2025, 12, 31)


# ── fixture helpers (mirroring test_ar_aging_combined.py / test_aging_as_of_date.py) ──

def _customer(db_session, code, name=None):
    c = Customer(code=code, name=name or f'Cust {code}', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, branch_id, number, total,
             invoice_date=None, customer_name=None):
    d = invoice_date or date(2025, 11, 1)
    inv = SalesInvoice(
        branch_id=branch_id, invoice_number=number,
        invoice_date=d, due_date=d,
        customer_id=customer.id,
        customer_name=customer_name or customer.name,
        notes='', status='posted',
        amount_paid=Decimal('0.00'), balance=Decimal(str(total)),
        total_amount=Decimal(str(total)), subtotal=Decimal(str(total)),
        vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


def _memo(db_session, customer, invoice, number, total, memo_date=None):
    """A posted debit memo referencing `invoice` (sales_invoice_id is
    nullable=False -- every memo always references a posted invoice)."""
    m = SalesMemo(
        branch_id=invoice.branch_id, memo_type='debit', memo_number=number,
        memo_date=memo_date or date(2025, 11, 1),
        sales_invoice_id=invoice.id, original_invoice_number=invoice.invoice_number,
        customer_id=customer.id, customer_name=customer.name,
        reason='Undercharge', notes='', destination='ar',
        subtotal=Decimal(str(total)), vat_amount=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal(str(total)),
        amount_paid=Decimal('0.00'), balance=Decimal(str(total)),
        status='posted',
    )
    db_session.add(m)
    db_session.commit()
    return m


def _any_account(db_session):
    """A cash account for CRV headers (cash_account_id is NOT NULL)."""
    acct = Account.query.filter_by(code='DM-AGING-CASH').first()
    if acct is None:
        acct = Account(code='DM-AGING-CASH', name='Debit Memo Aging Test Cash',
                       account_type='Asset', classification='Current Asset',
                       normal_balance='Debit', is_active=True)
        db_session.add(acct)
        db_session.commit()
    return acct


def _settle_memo(db_session, memo, branch_id, crv_number, crv_date, amount,
                  status='posted', cash_account_id=None):
    """Record a cash receipt settling a debit memo, mirroring what posting
    does: a CRVArLine with sales_memo_id set and invoice_id left NULL."""
    if cash_account_id is None:
        cash_account_id = _any_account(db_session).id
    crv = CashReceiptVoucher(
        branch_id=branch_id, crv_number=crv_number, crv_date=crv_date,
        customer_id=memo.customer_id, customer_name=memo.customer_name,
        payment_method='cash', cash_account_id=cash_account_id,
        notes='', status=status,
        total_ar_applied=Decimal(str(amount)), total_revenue=Decimal('0.00'),
        total_vat=Decimal('0.00'), total_wt=Decimal('0.00'),
        total_amount=Decimal(str(amount)),
    )
    db_session.add(crv)
    db_session.flush()
    db_session.add(CRVArLine(
        crv_id=crv.id, line_number=1, sales_memo_id=memo.id,
        invoice_number=memo.memo_number,
        original_balance=Decimal(str(memo.total_amount)),
        amount_applied=Decimal(str(amount)),
    ))
    db_session.commit()
    return crv


def _settle_invoice(db_session, invoice, branch_id, crv_number, crv_date, amount,
                     status='posted', cash_account_id=None):
    """Record a cash receipt settling an invoice -- invoice_id set, sales_memo_id NULL."""
    if cash_account_id is None:
        cash_account_id = _any_account(db_session).id
    crv = CashReceiptVoucher(
        branch_id=branch_id, crv_number=crv_number, crv_date=crv_date,
        customer_id=invoice.customer_id, customer_name=invoice.customer_name,
        payment_method='cash', cash_account_id=cash_account_id,
        notes='', status=status,
        total_ar_applied=Decimal(str(amount)), total_revenue=Decimal('0.00'),
        total_vat=Decimal('0.00'), total_wt=Decimal('0.00'),
        total_amount=Decimal(str(amount)),
    )
    db_session.add(crv)
    db_session.flush()
    db_session.add(CRVArLine(
        crv_id=crv.id, line_number=1, invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        original_balance=Decimal(str(invoice.total_amount)),
        amount_applied=Decimal(str(amount)),
    ))
    db_session.commit()
    return crv


class TestMemoSettledAsOf:

    def test_memo_settled_by_a_posted_crv_on_or_before_the_date_counts(
            self, db_session, main_branch):
        c = _customer(db_session, 'DM1')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM1', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-00001', Decimal('560.00'))
        _settle_memo(db_session, memo, main_branch.id, 'CR-DM1', AS_OF, Decimal('200.00'))
        result = _memo_settled_as_of([memo.id], AS_OF)
        assert result == {memo.id: Decimal('200.00')}

    def test_memo_settled_after_the_as_of_date_does_not_count(
            self, db_session, main_branch):
        c = _customer(db_session, 'DM2')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM2', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-00002', Decimal('560.00'))
        _settle_memo(db_session, memo, main_branch.id, 'CR-DM2',
                     AS_OF + timedelta(days=1), Decimal('200.00'))
        result = _memo_settled_as_of([memo.id], AS_OF)
        assert result == {}

    def test_memo_settled_by_a_cancelled_crv_does_not_count(
            self, db_session, main_branch):
        c = _customer(db_session, 'DM3')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM3', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-00003', Decimal('560.00'))
        _settle_memo(db_session, memo, main_branch.id, 'CR-DM3', AS_OF,
                     Decimal('200.00'), status='cancelled')
        result = _memo_settled_as_of([memo.id], AS_OF)
        assert result == {}

    def test_empty_memo_ids_returns_empty(self, db_session):
        assert _memo_settled_as_of([], AS_OF) == {}

    def test_invoice_settlement_is_unaffected(self, db_session, main_branch):
        """A memo-settling CRV line must not leak into `_ar_settled_as_of`'s
        invoice-keyed results -- the guard proving the two lookups stay
        genuinely separate."""
        c = _customer(db_session, 'DM4')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM4', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-00004', Decimal('560.00'))
        _settle_invoice(db_session, inv, main_branch.id, 'CR-DM4-INV', AS_OF, Decimal('400.00'))
        _settle_memo(db_session, memo, main_branch.id, 'CR-DM4-MEMO', AS_OF, Decimal('300.00'))

        # Query invoice settlement for BOTH ids (guards against a false match
        # via any accidental id collision between the two tables' PKs).
        inv_result = _ar_settled_as_of([inv.id, memo.id], AS_OF)
        assert inv_result == {inv.id: Decimal('400.00')}

        memo_result = _memo_settled_as_of([memo.id], AS_OF)
        assert memo_result == {memo.id: Decimal('300.00')}


class TestMemoDerivedDueDate:
    """Unit tests for the pure derivation, including the null-due-date
    fallback. `SalesInvoice.due_date` is `nullable=False` in the current
    model/migrated schema (so a real invoice row cannot be persisted with
    due_date=None through db_session/create_all() in this suite) -- this
    is tested as a pure function of dates, not via a DB row, for exactly
    that reason. The design doc's stated fallback (a real invoice row
    with due_date unset, e.g. from schema drift or a legacy bulk import
    that bypassed ORM validation) is still covered: the function's
    behaviour is identical either way, it just takes its inputs directly
    instead of via `invoice.due_date`."""

    def test_derives_from_the_invoice_terms_interval(self):
        result = _memo_derived_due_date(
            date(2025, 11, 15), date(2025, 10, 1), date(2025, 10, 31))
        assert result == date(2025, 12, 15)

    def test_memo_with_no_invoice_due_date_falls_back_to_memo_date(self):
        result = _memo_derived_due_date(
            date(2025, 11, 15), date(2025, 10, 1), None)
        assert result == date(2025, 11, 15)


class TestBuildArAgingDataWithMemos:
    """Union of posted debit memos into `_build_ar_aging_data`, per
    docs/superpowers/specs/2026-08-01-ar-aging-debit-memos-design.md."""

    def test_a_debit_memo_appears_as_its_own_row(self, db_session, main_branch):
        c = _customer(db_session, 'DM10')
        _invoice(db_session, c, main_branch.id, 'SI-DM10', Decimal('1000.00'))
        _memo(db_session, c, _invoice(db_session, c, main_branch.id, 'SI-DM10-REF',
                                      Decimal('1.00')), 'DM-10001', Decimal('300.00'))
        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert len(rows) == 1
        by_num = {i['invoice_number']: i for i in rows[0]['invoices']}
        assert by_num['SI-DM10']['doc_type'] == 'invoice'
        assert by_num['DM-10001']['doc_type'] == 'debit_memo'
        assert len(rows[0]['invoices']) == 3

    def test_memo_buckets_on_the_derived_due_date(self, db_session, main_branch):
        """The case that motivated the spec revision: an invoice and a memo
        raised the SAME DAY on 30-day terms must land in the SAME bucket."""
        c1 = _customer(db_session, 'DM20')
        c2 = _customer(db_session, 'DM21')
        ref_invoice = _invoice(db_session, c1, main_branch.id, 'SI-DM20-REF',
                               Decimal('500.00'), invoice_date=date(2025, 10, 1))
        ref_invoice.due_date = date(2025, 10, 31)  # 30-day terms
        db_session.commit()
        memo = _memo(db_session, c1, ref_invoice, 'DM-20001', Decimal('300.00'),
                    memo_date=date(2025, 11, 15))
        # derived due = 2025-11-15 + 30 days = 2025-12-15

        test_invoice = _invoice(db_session, c2, main_branch.id, 'SI-DM21',
                                Decimal('700.00'), invoice_date=date(2025, 11, 15))
        test_invoice.due_date = date(2025, 12, 15)  # same 30-day terms, same raise day
        db_session.commit()

        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id])
        by_num = {}
        for row in rows:
            for i in row['invoices']:
                by_num[i['invoice_number']] = i

        assert by_num['DM-20001']['due_date'] == date(2025, 12, 15)
        assert by_num['DM-20001']['bucket'] == by_num['SI-DM21']['bucket']

    def test_fully_settled_memo_is_excluded(self, db_session, main_branch):
        c = _customer(db_session, 'DM11')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM11', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-11001', Decimal('300.00'))
        _settle_memo(db_session, memo, main_branch.id, 'CR-DM11', AS_OF, Decimal('300.00'))
        rows, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        numbers = [i['invoice_number'] for i in rows[0]['invoices']]
        assert 'DM-11001' not in numbers
        assert totals['total'] == Decimal('1000.00')

    def test_credit_memos_are_never_included(self, db_session, main_branch):
        c = _customer(db_session, 'DM12')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM12', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'CM-12001', Decimal('300.00'))
        memo.memo_type = 'credit'
        db_session.commit()
        rows, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        numbers = [i['invoice_number'] for i in rows[0]['invoices']]
        assert 'CM-12001' not in numbers
        assert totals['total'] == Decimal('1000.00')

    def test_draft_and_voided_memos_are_excluded(self, db_session, main_branch):
        c = _customer(db_session, 'DM13')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM13', Decimal('1000.00'))
        draft_memo = _memo(db_session, c, inv, 'DM-13001', Decimal('100.00'))
        draft_memo.status = 'draft'
        voided_memo = _memo(db_session, c, inv, 'DM-13002', Decimal('100.00'))
        voided_memo.status = 'voided'
        db_session.commit()
        rows, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        numbers = [i['invoice_number'] for i in rows[0]['invoices']]
        assert 'DM-13001' not in numbers
        assert 'DM-13002' not in numbers
        assert totals['total'] == Decimal('1000.00')

    def test_memo_branch_is_inherited_from_the_referenced_invoice(
            self, db_session, main_branch, branch_manila):
        c = _customer(db_session, 'DM14')
        inv = _invoice(db_session, c, branch_manila.id, 'SI-DM14', Decimal('1000.00'))
        memo = _memo(db_session, c, inv, 'DM-14001', Decimal('300.00'))
        # Deliberately set the memo's OWN branch_id to a DIFFERENT branch, so
        # this test fails if the implementation reads memo.branch_id instead
        # of the referenced invoice's branch_id.
        memo.branch_id = main_branch.id
        db_session.commit()

        rows, _ = _build_ar_aging_data(AS_OF, None, include_branch=True)
        by_num = {i['invoice_number']: i for i in rows[0]['invoices']}
        assert by_num['DM-14001']['branch_id'] == branch_manila.id
        assert by_num['DM-14001']['branch_code'] == branch_manila.code

    def test_branch_restricted_user_sees_the_amount_but_cannot_drill_in(
            self, db_session, main_branch, branch_manila):
        c = _customer(db_session, 'DM15')
        inv = _invoice(db_session, c, branch_manila.id, 'SI-DM15', Decimal('1000.00'))
        _memo(db_session, c, inv, 'DM-15001', Decimal('300.00'))
        rows, totals = _build_ar_aging_data(
            AS_OF, None, include_branch=True, viewable_branch_ids={main_branch.id})
        by_num = {i['invoice_number']: i for i in rows[0]['invoices']}
        assert by_num['DM-15001']['viewable'] is False
        assert totals['total'] == Decimal('1300.00')

    def test_grand_total_equals_invoices_plus_memos_outstanding(
            self, db_session, main_branch):
        """The reconciliation invariant -- the gate for this task. Built
        independently of the builder's internals so it would fail if
        memos were either omitted (total too low) or double-counted
        (total too high)."""
        c1 = _customer(db_session, 'GT1')
        c2 = _customer(db_session, 'GT2')
        inv1 = _invoice(db_session, c1, main_branch.id, 'SI-GT1', Decimal('1000.00'))
        inv2 = _invoice(db_session, c2, main_branch.id, 'SI-GT2', Decimal('2000.00'))
        memo1 = _memo(db_session, c1, inv1, 'DM-GT1', Decimal('300.00'))
        memo2 = _memo(db_session, c2, inv2, 'DM-GT2', Decimal('150.00'))
        _settle_memo(db_session, memo2, main_branch.id, 'CR-GT1', AS_OF, Decimal('50.00'))
        _settle_invoice(db_session, inv2, main_branch.id, 'CR-GT2', AS_OF, Decimal('500.00'))

        expected_invoices_outstanding = (
            (Decimal('1000.00') - Decimal('0.00'))
            + (Decimal('2000.00') - Decimal('500.00')))
        expected_memos_outstanding = (
            (Decimal('300.00') - Decimal('0.00'))
            + (Decimal('150.00') - Decimal('50.00')))
        expected = expected_invoices_outstanding + expected_memos_outstanding

        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == expected

    def test_memos_group_under_the_same_customer_row_as_their_invoices(
            self, db_session, main_branch):
        c = _customer(db_session, 'DM16')
        inv = _invoice(db_session, c, main_branch.id, 'SI-DM16', Decimal('1000.00'))
        _memo(db_session, c, inv, 'DM-16001', Decimal('300.00'))
        rows, _ = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert len(rows) == 1
        assert rows[0]['total'] == Decimal('1300.00')
        numbers = {i['invoice_number'] for i in rows[0]['invoices']}
        assert numbers == {'SI-DM16', 'DM-16001'}
