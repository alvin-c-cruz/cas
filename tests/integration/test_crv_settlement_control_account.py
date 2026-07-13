"""CRVArLine settlement lines must inherit their AR-Trade account from the
specific SalesInvoice each line settles (falling back to the global default
for a Sales Memo debit-note settlement, which has no per-transaction field).
See docs/superpowers/specs/2026-07-12-cd-cr-control-account-resolution-design.md."""
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice
from app.sales_memos.models import SalesMemo
from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration]


def _account(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _posted_invoice(branch, customer, invoice_number, total, ar_trade_account_id):
    today = date.today()
    inv = SalesInvoice(
        branch_id=branch.id, invoice_number=invoice_number,
        invoice_date=today, due_date=today,
        customer_id=customer.id, customer_name=customer.name,
        status='posted', subtotal=total, total_before_wt=total,
        total_amount=total, amount_paid=Decimal('0.00'), balance=total,
        ar_trade_account_id=ar_trade_account_id,
    )
    db.session.add(inv); db.session.commit()
    return inv


def test_crv_settling_invoice_credits_the_invoices_own_account(
        db_session, accountant_user, main_branch):
    global_ar = _account('CRVS01', 'Global AR Trade', 'Asset', 'Debit')
    invoice_acct = _account('CRVS02', 'Invoice Own AR Trade', 'Asset', 'Debit')
    cash_acct = _account('CRVS03', 'Cash on Hand', 'Asset', 'Debit')
    assign_control_accounts(db_session, ar=global_ar.code)

    customer = Customer(code='CRVSC1', name='Settlement Test Customer', is_active=True)
    db.session.add(customer); db.session.commit()
    invoice = _posted_invoice(main_branch, customer, 'CRVS-SI-A', Decimal('500.00'), invoice_acct.id)

    crv = CashReceiptVoucher(
        branch_id=main_branch.id, crv_number='CRVS-0001', crv_date=date.today(),
        customer_id=customer.id, customer_name=customer.name, payment_method='cash',
        cash_account_id=cash_acct.id, notes='Settlement test', status='draft',
        total_ar_applied=Decimal('500.00'), total_amount=Decimal('500.00'),
    )
    db.session.add(crv); db.session.flush()
    db.session.add(CRVArLine(crv_id=crv.id, line_number=1, invoice_id=invoice.id,
                             invoice_number=invoice.invoice_number,
                             original_balance=invoice.balance, amount_applied=Decimal('500.00')))
    db.session.commit()
    db.session.refresh(crv)

    from app.cash_receipts.views import _post_crv_je
    je = _post_crv_je(crv, accountant_user.id)
    db.session.commit()

    matching = [l for l in je.lines if l.account_id == invoice_acct.id]
    assert len(matching) == 1 and matching[0].credit_amount == Decimal('500.00')
    assert not any(l.account_id == global_ar.id for l in je.lines)


def test_crv_settling_sales_memo_uses_global_default(db_session, accountant_user, main_branch):
    global_ar = _account('CRVS04', 'Global AR Trade 2', 'Asset', 'Debit')
    assign_control_accounts(db_session, ar=global_ar.code)

    customer = Customer(code='CRVSC2', name='Memo Settlement Customer', is_active=True)
    db.session.add(customer); db.session.commit()
    # SalesMemo always references an original invoice (sales_invoice_id/
    # original_invoice_number/reason are all NOT NULL) -- it is never fully
    # standalone, unlike a CDVExpenseLine/CRVRevenueLine.
    original_invoice = _posted_invoice(main_branch, customer, 'CRVS-SI-ORIG',
                                       Decimal('200.00'), None)
    memo = SalesMemo(
        branch_id=main_branch.id, memo_number='CRVS-DN-A', memo_type='debit',
        memo_date=date.today(), sales_invoice_id=original_invoice.id,
        original_invoice_number=original_invoice.invoice_number,
        customer_id=customer.id, customer_name=customer.name,
        reason='Test surcharge', status='posted',
        total_amount=Decimal('200.00'), balance=Decimal('200.00'),
    )
    db.session.add(memo); db.session.commit()

    cash_acct = _account('CRVS05', 'Cash on Hand 2', 'Asset', 'Debit')
    crv = CashReceiptVoucher(
        branch_id=main_branch.id, crv_number='CRVS-0002', crv_date=date.today(),
        customer_id=customer.id, customer_name=customer.name, payment_method='cash',
        cash_account_id=cash_acct.id, notes='Memo settlement test', status='draft',
        total_ar_applied=Decimal('200.00'), total_amount=Decimal('200.00'),
    )
    db.session.add(crv); db.session.flush()
    db.session.add(CRVArLine(crv_id=crv.id, line_number=1, sales_memo_id=memo.id,
                             invoice_number=memo.memo_number,
                             original_balance=memo.balance, amount_applied=Decimal('200.00')))
    db.session.commit()
    db.session.refresh(crv)

    from app.cash_receipts.views import _post_crv_je
    je = _post_crv_je(crv, accountant_user.id)
    db.session.commit()

    matching = [l for l in je.lines if l.account_id == global_ar.id]
    assert len(matching) == 1 and matching[0].credit_amount == Decimal('200.00')
