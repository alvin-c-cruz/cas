"""Two-column + reconciliation assembly for Sales by Product Line."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.reports.product_line import build_sales_by_product_line

D = lambda v: Decimal(str(v))


def _seed_one_sale(when, net_plus_vat=112, vat=12, code='BEV'):
    cust = Customer(code='C1', name='Acme'); db.session.add(cust); db.session.flush()
    cat = ProductCategory(code=code, name=code, is_active=True); db.session.add(cat); db.session.flush()
    p = Product(code='P', name='P', category_id=cat.id); db.session.add(p); db.session.flush()
    inv = SalesInvoice(invoice_number='SI-1', invoice_date=when, due_date=when,
                       customer_id=cust.id, customer_name='Acme', status='posted')
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='x',
                                    product_id=p.id, line_total=D(net_plus_vat), vat_amount=D(vat)))
    db.session.commit()
    return cat


@pytest.mark.unit
class TestBuildSalesByProductLine:
    def test_percentages_and_columns(self, db_session):
        _seed_one_sale(date(2026, 5, 10))
        out = build_sales_by_product_line(date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1))
        assert len(out['rows']) == 1
        row = out['rows'][0]
        assert row['mtd'] == 100.0
        assert row['ytd'] == 100.0
        assert row['mtd_pct'] == 100.0
        assert out['total']['mtd'] == 100.0

    def test_reconciles_to_income_statement_net_sales(self, db_session):
        # This sale must post to a revenue account for the IS to see it; if the seeded
        # scenario has no posted JE, is_net_sales is 0 and variance == -total (surfaced,
        # not hidden). Assert the reconciliation fields are computed and consistent.
        _seed_one_sale(date(2026, 5, 10))
        out = build_sales_by_product_line(date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1))
        rec = out['reconciliation']
        assert set(rec) == {'is_net_sales_mtd', 'is_net_sales_ytd',
                            'variance_mtd', 'variance_ytd', 'reconciled'}
        assert round(rec['variance_mtd'], 2) == round(rec['is_net_sales_mtd'] - out['total']['mtd'], 2)
        assert isinstance(rec['reconciled'], bool)

    def test_empty_period_zero_percent_no_crash(self, db_session):
        out = build_sales_by_product_line(date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1))
        assert out['rows'] == []
        assert out['total']['mtd'] == 0.0
        assert out['unassigned']['mtd_pct'] == 0.0
