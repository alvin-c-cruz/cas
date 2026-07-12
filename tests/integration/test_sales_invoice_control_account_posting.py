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


def test_post_invoice_uses_document_creditable_wht_override_not_global(
        db_session, accountant_user, main_branch):
    ar = _account('SICP04', 'AR Trade', 'Asset', 'Debit')
    global_wht = _account('SICP05', 'Global Creditable WHT', 'Asset', 'Debit')
    override_wht = _account('SICP06', 'Override Creditable WHT', 'Asset', 'Debit')
    revenue = _account('SICP07', 'Revenue', 'Revenue', 'Credit')
    assign_control_accounts(db_session, creditable_wht=global_wht.code)

    customer = Customer(code='SICPC2', name='WHT Override Customer', is_active=True)
    db.session.add(customer); db.session.commit()

    invoice = SalesInvoice(
        branch_id=main_branch.id, invoice_number='SICP-0002',
        invoice_date=date.today(), due_date=date.today(),
        customer_id=customer.id, customer_name=customer.name,
        status='draft', ar_trade_account_id=ar.id,
        creditable_wht_account_id=override_wht.id,
        subtotal=Decimal('1000.00'), total_before_wt=Decimal('1000.00'),
        withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('980.00'),
    )
    db.session.add(invoice); db.session.commit()

    # A revenue line item is required so _post_invoice_je has a credit leg to
    # balance against the AR + Creditable WHT debit legs (mirrors the AR
    # override test above).
    line_item = SalesInvoiceItem(
        invoice_id=invoice.id, line_number=1, description='Test line',
        amount=Decimal('1000.00'), line_total=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), account_id=revenue.id,
    )
    db.session.add(line_item); db.session.commit()

    from app.sales_invoices.views import _post_invoice_je
    je = _post_invoice_je(invoice, accountant_user.id)
    db.session.commit()

    wht_lines = [l for l in je.lines if l.account_id == override_wht.id]
    assert len(wht_lines) == 1
    assert wht_lines[0].debit_amount == Decimal('20.00')
    assert not any(l.account_id == global_wht.id for l in je.lines)


def test_preview_uses_document_ar_trade_and_creditable_wht_overrides_not_global(
        db_session, accountant_user, main_branch):
    global_ar = _account('SICP08', 'Global AR Trade', 'Asset', 'Debit')
    override_ar = _account('SICP09', 'Override AR Trade', 'Asset', 'Debit')
    global_wht = _account('SICP10', 'Global Creditable WHT', 'Asset', 'Debit')
    override_wht = _account('SICP11', 'Override Creditable WHT', 'Asset', 'Debit')
    revenue = _account('SICP12', 'Revenue', 'Revenue', 'Credit')
    assign_control_accounts(db_session, ar=global_ar.code, creditable_wht=global_wht.code)

    customer = Customer(code='SICPC3', name='Preview Override Customer', is_active=True)
    db.session.add(customer); db.session.commit()

    # DRAFT invoice with no stored journal_entry yet -> _build_je_preview takes
    # the inline-compute path, which must read the invoice's own override
    # accounts rather than the global control-account settings.
    invoice = SalesInvoice(
        branch_id=main_branch.id, invoice_number='SICP-0003',
        invoice_date=date.today(), due_date=date.today(),
        customer_id=customer.id, customer_name=customer.name,
        status='draft', ar_trade_account_id=override_ar.id,
        creditable_wht_account_id=override_wht.id,
        subtotal=Decimal('1000.00'), total_before_wt=Decimal('1000.00'),
        withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('980.00'),
    )
    db.session.add(invoice); db.session.commit()

    line_item = SalesInvoiceItem(
        invoice_id=invoice.id, line_number=1, description='Test line',
        amount=Decimal('1000.00'), line_total=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), account_id=revenue.id,
    )
    db.session.add(line_item); db.session.commit()

    assert invoice.journal_entry is None

    from app.sales_invoices.views import _build_je_preview
    preview = _build_je_preview(invoice)

    codes = {row['code'] for row in preview}
    assert override_ar.code in codes
    assert override_wht.code in codes
    assert global_ar.code not in codes
    assert global_wht.code not in codes
