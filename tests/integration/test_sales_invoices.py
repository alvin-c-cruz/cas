import pytest
from decimal import Decimal
from datetime import date


@pytest.fixture
def customer(db_session):
    from app.customers.models import Customer
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def revenue_account(db_session):
    from app.accounts.models import Account
    a = Account(code='40001', name='Service Revenue', account_type='Revenue',
                normal_balance='credit', is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if not b:
        b = Branch(name='Main Branch', code='MB', is_active=True)
        db_session.add(b)
        db_session.commit()
    return b


def test_sales_invoice_has_required_fields(db_session, customer, branch):
    from app.sales_invoices.models import SalesInvoice
    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-0001',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    assert inv.journal_entry_id is None
    assert inv.withholding_tax_amount == Decimal('0.00')
    assert inv.vat_override is False
    assert inv.wt_override is False
    assert inv.total_before_wt == Decimal('0.00')
    assert inv.customer_po_number is None


def test_sales_invoice_calculate_totals_no_items(db_session, customer, branch):
    """calculate_totals() with no line items zeros all totals (PurchaseBill pattern)."""
    from app.sales_invoices.models import SalesInvoice
    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-0002',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    inv.calculate_totals()
    assert inv.subtotal == Decimal('0.00')
    assert inv.total_before_wt == Decimal('0.00')
    assert inv.total_amount == Decimal('0.00')
    assert inv.balance == Decimal('0.00')


@pytest.fixture
def wht_code(db_session):
    from app.withholding_tax.models import WithholdingTax
    w = WithholdingTax(code='WC010', name='EWT 10%', rate=Decimal('10.00'), is_active=True)
    db_session.add(w)
    db_session.commit()
    return w


def test_invoice_item_calculate_amounts_vat_inclusive(db_session, revenue_account, wht_code):
    from app.sales_invoices.models import SalesInvoiceItem
    item = SalesInvoiceItem(
        line_number=1,
        description='Service',
        amount=Decimal('11200.00'),
        vat_rate=Decimal('12.00'),
        wt_rate=Decimal('10.00'),
        account_id=revenue_account.id,
    )
    item.calculate_amounts()
    # VAT-inclusive: net_base = 11200 / 1.12 = 10000
    net_base = Decimal('11200.00') / Decimal('1.12')
    expected_vat = (Decimal('11200.00') - net_base).quantize(Decimal('0.01'))
    expected_wt = (net_base * Decimal('0.10')).quantize(Decimal('0.01'))
    assert item.line_total == Decimal('11200.00')
    assert abs(item.vat_amount - expected_vat) < Decimal('0.02')
    assert abs(item.wt_amount - expected_wt) < Decimal('0.02')


def test_invoice_item_zero_vat(db_session, revenue_account):
    from app.sales_invoices.models import SalesInvoiceItem
    item = SalesInvoiceItem(
        line_number=1,
        description='Exempt Service',
        amount=Decimal('5000.00'),
        vat_rate=Decimal('0.00'),
        account_id=revenue_account.id,
    )
    item.calculate_amounts()
    assert item.line_total == Decimal('5000.00')
    assert item.vat_amount == Decimal('0.00')
    assert item.wt_amount == Decimal('0.00')


def test_invoice_attachment_model_structure(db_session):
    from app.sales_invoices.models import SalesInvoiceAttachment
    col_names = [c.name for c in SalesInvoiceAttachment.__table__.columns]
    assert 'invoice_id' in col_names
    assert 'stored_filename' in col_names
    assert 'mime_type' in col_names
    assert 'file_size' in col_names
    assert 'uploaded_by_id' in col_names
