from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.reports.income_statement_by_product_line import (
    _standard_cogs_by_category, _units_sold_by_category, _revenue_by_category, _categories)

pytestmark = [pytest.mark.unit]

D = lambda v: Decimal(str(v))


def _seed_si(cat_code, qty, standard_cost, line_total=112, vat=12, invoice_number='SI-1'):
    cust = Customer(code=f'C-{invoice_number}', name='Acme'); db.session.add(cust); db.session.flush()
    cat = ProductCategory.query.filter_by(code=cat_code).first()
    if not cat:
        cat = ProductCategory(code=cat_code, name=cat_code, is_active=True)
        db.session.add(cat); db.session.flush()
    p = Product(code=f'P-{invoice_number}', name='P', category_id=cat.id,
               standard_cost=(D(standard_cost) if standard_cost is not None else None))
    db.session.add(p); db.session.flush()
    inv = SalesInvoice(invoice_number=invoice_number, invoice_date=date(2026, 5, 10),
                       due_date=date(2026, 5, 10), customer_id=cust.id, customer_name='Acme',
                       status='posted')
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='x',
                                    product_id=p.id, quantity=D(qty),
                                    line_total=D(line_total), vat_amount=D(vat)))
    db.session.commit()
    return cat


class TestStandardCogsByCategory:
    def test_single_line(self, db_session):
        cat = _seed_si('BEV', qty=10, standard_cost=5)
        out = _standard_cogs_by_category(date(2026, 5, 1), date(2026, 5, 31), None)
        assert out[cat.id] == D(50)

    def test_uncosted_product_contributes_zero(self, db_session):
        cat = _seed_si('BEV', qty=10, standard_cost=None)
        out = _standard_cogs_by_category(date(2026, 5, 1), date(2026, 5, 31), None)
        assert out.get(cat.id, D(0)) == D(0)

    def test_non_itemized_line_contributes_zero(self, db_session):
        cust = Customer(code='C2', name='Acme'); db.session.add(cust); db.session.flush()
        inv = SalesInvoice(invoice_number='SI-NI', invoice_date=date(2026, 5, 10),
                           due_date=date(2026, 5, 10), customer_id=cust.id, customer_name='Acme',
                           status='posted')
        db.session.add(inv); db.session.flush()
        db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='electricity',
                                        line_total=D(112), vat_amount=D(12)))
        db.session.commit()
        out = _standard_cogs_by_category(date(2026, 5, 1), date(2026, 5, 31), None)
        assert out == {}


class TestUnitsSoldByCategory:
    def test_counts_si_quantity(self, db_session):
        cat = _seed_si('BEV', qty=7, standard_cost=1)
        out = _units_sold_by_category(date(2026, 5, 1), date(2026, 5, 31), None)
        assert out[cat.id] == D(7)


class TestRevenueByCategory:
    def test_matches_sales_by_product_line_report(self, db_session):
        cat = _seed_si('BEV', qty=1, standard_cost=1)
        out = _revenue_by_category(date(2026, 5, 1), date(2026, 5, 31), None)
        assert out[cat.id] == D(100)  # 112 - 12 vat, net-of-vat, matches generate_sales_by_product_line


class TestCategories:
    def test_includes_inactive_categories(self, db_session):
        active = ProductCategory(code='ACT', name='Active', is_active=True)
        inactive = ProductCategory(code='INA', name='Inactive', is_active=False)
        db.session.add_all([active, inactive])
        db.session.commit()
        cats = _categories()
        assert active.id in cats
        assert inactive.id in cats
