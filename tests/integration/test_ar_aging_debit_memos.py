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
from app.reports.views import _memo_settled_as_of, _ar_settled_as_of

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
