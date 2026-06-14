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


def test_post_invoice_je_creates_balanced_entry(db_session, customer, revenue_account, branch, accountant_user):
    """_post_invoice_je creates a balanced JE with correct debit/credit structure."""
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory

    # Create required GL accounts
    ar = Account.query.filter_by(code='10201').first()
    if not ar:
        ar = Account(code='10201', name='AR - Trade', account_type='Asset',
                     normal_balance='debit', is_active=True)
        db_session.add(ar)

    output_vat = Account.query.filter_by(code='20201').first()
    if not output_vat:
        output_vat = Account(code='20201', name='Output VAT', account_type='Liability',
                             normal_balance='credit', is_active=True)
        db_session.add(output_vat)
    db_session.flush()

    vat_cat = VATCategory.query.filter_by(code='V12TEST').first()
    if not vat_cat:
        vat_cat = VATCategory(code='V12TEST', name='VAT 12% Test', rate=Decimal('12.00'),
                              output_vat_account_id=output_vat.id)
        db_session.add(vat_cat)
    db_session.flush()

    inv = SalesInvoice(
        branch_id=branch.id,
        invoice_number='SI-2026-JE01',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=customer.id,
        customer_name=customer.name,
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.flush()

    item = SalesInvoiceItem(
        invoice_id=inv.id, line_number=1, description='Service',
        amount=Decimal('11200.00'), vat_category='V12TEST',
        vat_rate=Decimal('12.00'), account_id=revenue_account.id,
    )
    item.calculate_amounts()
    db_session.add(item)
    db_session.flush()
    inv.calculate_totals()

    from app.sales_invoices import views as sv_views
    je = sv_views._post_invoice_je(inv, accountant_user.id)
    db_session.flush()

    assert je.is_balanced
    assert je.total_debit == je.total_credit
    # AR is a debit; revenue + output VAT are credits
    debit_lines = [l for l in je.lines if l.debit_amount > 0]
    credit_lines = [l for l in je.lines if l.credit_amount > 0]
    assert len(debit_lines) >= 1  # AR at minimum
    assert len(credit_lines) >= 1  # Revenue at minimum


def test_create_invoice_posts_to_books(client, db_session, accountant_user, customer, revenue_account, branch):
    """Creating an SV saves draft JE and audit log entry."""
    from app.accounts.models import Account
    from app.audit.models import AuditLog
    from app.sales_invoices.models import SalesInvoice
    import json as _json

    # Ensure GL accounts exist
    if not Account.query.filter_by(code='10201').first():
        db_session.add(Account(code='10201', name='AR - Trade', account_type='Asset',
                               normal_balance='debit', is_active=True))
    if not Account.query.filter_by(code='20201').first():
        db_session.add(Account(code='20201', name='Output VAT', account_type='Liability',
                               normal_balance='credit', is_active=True))
    db_session.commit()

    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
        sess['_user_id'] = str(accountant_user.id)

    line_item = {
        'description': 'Consulting', 'amount': '11200.00',
        'vat_category': '', 'vat_rate': '0', 'wt_id': '', 'account_id': str(revenue_account.id),
    }
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-2026-0001',
        'invoice_date': '2026-06-14',
        'due_date': '2026-07-14',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': 'Test invoice',
        'line_items': _json.dumps([line_item]),
    })

    assert resp.status_code == 302
    inv = SalesInvoice.query.filter_by(invoice_number='SI-2026-0001').first()
    assert inv is not None
    assert inv.journal_entry_id is not None
    assert inv.total_amount == Decimal('11200.00')

    audit = AuditLog.query.filter_by(module='sales_invoice', action='create',
                                     record_id=inv.id).first()
    assert audit is not None
    assert audit.user_id == accountant_user.id
