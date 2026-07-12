import json
import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def _account(code, name, atype, nb):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def test_post_invoice_uses_document_ar_trade_override_not_global(
        db_session, accountant_user, main_branch):
    global_ar = _account('SICP01', 'Global AR Trade', 'Asset', 'Debit')
    override_ar = _account('SICP02', 'Override AR Trade', 'Asset', 'Debit')
    revenue = _account('SICP03', 'Revenue', 'Revenue', 'Credit')
    assign_control_accounts(db_session, ar=global_ar.code)

    customer = Customer(code='SICPC1', name='Posting Field Customer', is_active=True)
    db.session.add(customer); db.session.commit()

    invoice = SalesInvoice(
        branch_id=main_branch.id, invoice_number='SICP-0001',
        invoice_date=date.today(), due_date=date.today(),
        customer_id=customer.id, customer_name=customer.name,
        status='draft', ar_trade_account_id=override_ar.id,
        subtotal=Decimal('1000.00'), total_before_wt=Decimal('1000.00'),
        total_amount=Decimal('1000.00'),
    )
    db.session.add(invoice); db.session.commit()

    # A revenue line item is required so _post_invoice_je has a credit leg to
    # balance against the AR debit leg (an invoice with no line items has no
    # revenue account to absorb the JE, so it raises "not balanced" regardless
    # of which AR account is targeted — unrelated to the override behavior
    # under test here).
    line_item = SalesInvoiceItem(
        invoice_id=invoice.id, line_number=1, description='Test line',
        amount=Decimal('1000.00'), line_total=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), account_id=revenue.id,
    )
    db.session.add(line_item); db.session.commit()

    from app.sales_invoices.views import _post_invoice_je
    je = _post_invoice_je(invoice, accountant_user.id)
    db.session.commit()

    ar_lines = [l for l in je.lines if l.account_id == override_ar.id]
    assert len(ar_lines) == 1
    assert ar_lines[0].debit_amount == Decimal('1000.00')
    assert not any(l.account_id == global_ar.id for l in je.lines)
