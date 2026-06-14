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


def test_sales_invoice_calculate_totals_no_wht(db_session, customer, branch):
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
        subtotal=Decimal('11200.00'),
        vat_amount=Decimal('1200.00'),
        withholding_tax_amount=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    inv.calculate_totals()
    assert inv.total_before_wt == Decimal('11200.00')
    assert inv.total_amount == Decimal('11200.00')
    assert inv.balance == Decimal('11200.00')
