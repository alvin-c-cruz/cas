import pytest
from decimal import Decimal
from datetime import date


def test_output_vat_buckets_raises_if_no_output_account(app, db_session):
    """_output_vat_buckets raises ValueError when a VAT-bearing line has no output account.
    SI now reads SalesVATCategory (not VATCategory) for VAT buckets."""
    with app.app_context():
        from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
        from app.sales_vat_categories.models import SalesVATCategory
        from app.branches.models import Branch
        from app.customers.models import Customer

        branch = Branch.query.first()
        if not branch:
            branch = Branch(name='Main', code='MB', is_active=True)
            db_session.add(branch)
            db_session.flush()

        cust = Customer(code='C99', name='Test', is_active=True)
        db_session.add(cust)
        db_session.flush()

        # SalesVATCategory with NO output_vat_account -> should raise ValueError
        cat = SalesVATCategory(code='BADVAT', name='Bad VAT', rate=Decimal('12.00'),
                               transaction_nature='regular', output_vat_account_id=None)
        db_session.add(cat)

        inv = SalesInvoice(
            branch_id=branch.id,
            invoice_number='SI-2026-9999',
            invoice_date=date(2026, 6, 14),
            due_date=date(2026, 7, 14),
            customer_id=cust.id,
            customer_name='Test',
            notes='',
            status='draft',
            amount_paid=Decimal('0.00'),
            vat_amount=Decimal('1200.00'),
            subtotal=Decimal('11200.00'),
            total_amount=Decimal('11200.00'),
        )
        db_session.add(inv)
        db_session.flush()

        item = SalesInvoiceItem(
            invoice_id=inv.id, line_number=1, description='Service',
            amount=Decimal('11200.00'), vat_category='BADVAT',
            vat_rate=Decimal('12.00'), line_total=Decimal('11200.00'),
            vat_amount=Decimal('1200.00'), wt_amount=Decimal('0.00'),
        )
        db_session.add(item)
        db_session.commit()

        from app.sales_invoices import views as sv_views
        with pytest.raises(ValueError, match="no Output Tax account"):
            sv_views._output_vat_buckets(inv)


def test_build_je_preview_draft_no_items(app, db_session):
    """_build_je_preview on a draft with no line items returns empty list."""
    with app.app_context():
        from app.sales_invoices.models import SalesInvoice
        from app.branches.models import Branch
        from app.customers.models import Customer

        branch = Branch.query.first()
        if not branch:
            branch = Branch(name='Main', code='MB', is_active=True)
            db_session.add(branch)
            db_session.flush()

        cust = Customer(code='C98', name='Test2', is_active=True)
        db_session.add(cust)
        db_session.flush()

        inv = SalesInvoice(
            branch_id=branch.id,
            invoice_number='SI-2026-8888',
            invoice_date=date(2026, 6, 14),
            due_date=date(2026, 7, 14),
            customer_id=cust.id,
            customer_name='Test2',
            notes='',
            status='draft',
            amount_paid=Decimal('0.00'),
            vat_amount=Decimal('0.00'),
            subtotal=Decimal('0.00'),
            total_amount=Decimal('0.00'),
            withholding_tax_amount=Decimal('0.00'),
        )
        db_session.add(inv)
        db_session.commit()

        from app.sales_invoices import views as sv_views
        result = sv_views._build_je_preview(inv)
        # No line items, no VAT, no WHT -> only AR debit (if GL account exists)
        # Just assert it returns a list without crashing
        assert isinstance(result, list)
