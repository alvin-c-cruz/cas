"""The AR/AP aging reports must be TRUE point-in-time reports.

Both `_build_ar_aging_data` and `_build_ap_aging_data` historically used the
`as_of_date` argument ONLY to pick an ageing bucket. The document set and the
outstanding amount both came from live state:

  * no filter on document date, so a document dated AFTER as_of_date was still
    counted -- an invoice raised in 2026 appeared in an "as of 2025-12-31"
    report; and
  * the live `balance` column was used, so a collection/payment recorded AFTER
    as_of_date had already reduced the figure, and a document fully settled
    after as_of_date vanished from the report entirely (its status became
    'paid' and its balance 0).

Together these made it impossible to reproduce a past period-end AR/AP figure,
which is exactly what a client's own aging workbook records. Found while
reconciling RIC's AR against `2025-12 Aging of Accounts Receivable.xlsx`:
the report returned 200.9M against a workbook figure of 124.4M.

These tests pin the point-in-time contract for both reports.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from app.reports.views import _build_ar_aging_data, _build_ap_aging_data

pytestmark = [pytest.mark.integration]

AS_OF = date(2025, 12, 31)


# ── helpers ──────────────────────────────────────────────────────────────────

def _any_account(db_session):
    """A cash account for CRV headers (cash_account_id is NOT NULL)."""
    from app.accounts.models import Account
    acct = Account.query.filter_by(code='AGING-CASH').first()
    if acct is None:
        acct = Account(code='AGING-CASH', name='Aging Test Cash',
                       account_type='Asset', classification='Current Asset',
                       normal_balance='Debit', is_active=True)
        db_session.add(acct)
        db_session.commit()
    return acct


def _customer(db_session, code='CAG1'):
    c = Customer(code=code, name=f'Cust {code}', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, branch_id, number, invoice_date, total,
             paid=Decimal('0.00'), status='posted'):
    inv = SalesInvoice(
        branch_id=branch_id, invoice_number=number,
        invoice_date=invoice_date, due_date=invoice_date,
        customer_id=customer.id, customer_name=customer.name, notes='',
        status=status,
        amount_paid=Decimal(str(paid)),
        balance=Decimal(str(total)) - Decimal(str(paid)),
        total_amount=Decimal(str(total)), subtotal=Decimal(str(total)),
        vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


def _collect(db_session, invoice, branch_id, crv_number, crv_date, amount,
             status='posted', cash_account_id=None):
    if cash_account_id is None:
        cash_account_id = _any_account(db_session).id
    """Record a cash receipt against an invoice, mirroring what posting does."""
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
    # mirror _apply_ar_collections' effect on live state. A cancelled CRV has
    # had _reverse_ar_collections applied, so live state is left untouched --
    # only its row survives, which is exactly what the report must ignore.
    if status == 'posted':
        invoice.amount_paid = Decimal(str(invoice.amount_paid)) + Decimal(str(amount))
        invoice.balance = Decimal(str(invoice.total_amount)) - invoice.amount_paid
        invoice.status = 'paid' if invoice.balance <= 0 else 'partially_paid'
    db_session.commit()
    return crv


# ── AR ───────────────────────────────────────────────────────────────────────

class TestARAgingIsPointInTime:

    def test_excludes_invoice_dated_after_as_of(self, db_session, main_branch):
        """An invoice raised after the as-of date did not exist yet."""
        c = _customer(db_session)
        _invoice(db_session, c, main_branch.id, 'SI-FUTURE',
                 date(2026, 3, 1), Decimal('5000.00'))
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('0.00')

    def test_includes_invoice_dated_on_as_of(self, db_session, main_branch):
        c = _customer(db_session)
        _invoice(db_session, c, main_branch.id, 'SI-ONDATE',
                 AS_OF, Decimal('1234.56'))
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('1234.56')

    def test_ignores_collection_recorded_after_as_of(self, db_session, main_branch):
        """A 2026 receipt must not reduce the 2025-12-31 balance."""
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-PAIDLATER',
                       date(2025, 11, 10), Decimal('10000.00'))
        _collect(db_session, inv, main_branch.id, 'CRV-2026-1',
                 date(2026, 2, 15), Decimal('4000.00'))
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('10000.00')

    def test_fully_settled_after_as_of_still_appears(self, db_session, main_branch):
        """The regression that hid whole invoices: settled later => status 'paid',
        live balance 0, so the old code dropped it from a past-dated report."""
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-SETTLED',
                       date(2025, 9, 1), Decimal('7500.00'))
        _collect(db_session, inv, main_branch.id, 'CRV-2026-2',
                 date(2026, 1, 20), Decimal('7500.00'))
        assert inv.status == 'paid' and inv.balance == Decimal('0.00')
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('7500.00')

    def test_honours_collection_recorded_on_or_before_as_of(self, db_session, main_branch):
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-PARTPAID',
                       date(2025, 6, 1), Decimal('9000.00'))
        _collect(db_session, inv, main_branch.id, 'CRV-2025-1',
                 date(2025, 8, 30), Decimal('3500.00'))
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('5500.00')

    def test_settled_before_as_of_is_excluded(self, db_session, main_branch):
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-CLOSED',
                       date(2025, 4, 1), Decimal('2000.00'))
        _collect(db_session, inv, main_branch.id, 'CRV-2025-2',
                 date(2025, 5, 5), Decimal('2000.00'))
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('0.00')

    def test_cancelled_receipt_does_not_reduce_balance(self, db_session, main_branch, cash_account):
        """Only POSTED receipts settle AR; a cancelled CRV must be ignored."""
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-CANCRV',
                       date(2025, 7, 1), Decimal('6000.00'))
        _collect(db_session, inv, main_branch.id, 'CRV-CANC',
                 date(2025, 8, 1), Decimal('6000.00'), status='cancelled',
                 cash_account_id=cash_account.id)
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('6000.00')

    def test_draft_invoice_never_counted(self, db_session, main_branch):
        c = _customer(db_session)
        _invoice(db_session, c, main_branch.id, 'SI-DRAFT',
                 date(2025, 5, 1), Decimal('999.00'), status='draft')
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['total'] == Decimal('0.00')

    def test_buckets_use_as_of_not_today(self, db_session, main_branch):
        """A 2025 invoice must age against as_of_date, not date.today()."""
        c = _customer(db_session)
        inv = _invoice(db_session, c, main_branch.id, 'SI-BUCKET',
                       date(2025, 11, 1), Decimal('800.00'))
        inv.due_date = date(2025, 12, 15)   # 16 days overdue at 2025-12-31
        db_session.commit()
        _, totals = _build_ar_aging_data(AS_OF, [main_branch.id])
        assert totals['1-30'] == Decimal('800.00')
        assert totals['total'] == Decimal('800.00')


# ── AP (same defect, same file) ──────────────────────────────────────────────

class TestAPAgingIsPointInTime:

    def _vendor(self, db_session, code='VAG1'):
        v = Vendor(code=code, name=f'Vendor {code}', is_active=True)
        db_session.add(v)
        db_session.commit()
        return v

    def _bill(self, db_session, vendor, branch_id, number, bill_date, total,
              paid=Decimal('0.00'), status='posted'):
        ap = AccountsPayable(
            branch_id=branch_id, ap_number=number,
            ap_date=bill_date, due_date=bill_date,
            vendor_id=vendor.id, vendor_name=vendor.name,
            payee_type='vendor', notes='', status=status,
            amount_paid=Decimal(str(paid)),
            balance=Decimal(str(total)) - Decimal(str(paid)),
            total_amount=Decimal(str(total)), subtotal=Decimal(str(total)),
            vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        )
        db_session.add(ap)
        db_session.commit()
        return ap

    def test_excludes_bill_dated_after_as_of(self, db_session, main_branch):
        v = self._vendor(db_session)
        self._bill(db_session, v, main_branch.id, 'APV-FUTURE',
                   date(2026, 4, 1), Decimal('3000.00'))
        _, totals = _build_ap_aging_data(AS_OF, main_branch.id)
        assert totals['total'] == Decimal('0.00')

    def test_includes_bill_dated_on_or_before_as_of(self, db_session, main_branch):
        v = self._vendor(db_session)
        self._bill(db_session, v, main_branch.id, 'APV-PAST',
                   date(2025, 10, 5), Decimal('4500.00'))
        _, totals = _build_ap_aging_data(AS_OF, main_branch.id)
        assert totals['total'] == Decimal('4500.00')
