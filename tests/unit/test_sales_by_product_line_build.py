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


def _seed_second_sale(when, code, net_plus_vat=112, vat=12):
    """Mirror of _seed_one_sale with distinct customer code / invoice number / product code
    so it can be seeded alongside _seed_one_sale in the same test without unique-constraint
    collisions (Customer.code, SalesInvoice.invoice_number, ProductCategory.code all unique)."""
    cust = Customer(code='C2', name='Bravo'); db.session.add(cust); db.session.flush()
    cat = ProductCategory(code=code, name=code, is_active=True); db.session.add(cat); db.session.flush()
    p = Product(code='P2', name='P2', category_id=cat.id); db.session.add(p); db.session.flush()
    inv = SalesInvoice(invoice_number='SI-2', invoice_date=when, due_date=when,
                       customer_id=cust.id, customer_name='Bravo', status='posted')
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='y',
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
        # Positive reconciled==True case: no sales + no posted JE -> total==0 and
        # IS net_sales==0 -> both variances are exactly 0, so the AND-tolerance check
        # (abs(var_mtd) < 0.01 and abs(var_ytd) < 0.01) is exercised on the True side.
        rec = out['reconciliation']
        assert rec['variance_mtd'] == 0.0
        assert rec['variance_ytd'] == 0.0
        assert rec['reconciled'] is True

    def test_ytd_only_category_row_present_with_zero_mtd(self, db_session):
        # BEV: sale falls within the May MTD window [2026-05-01, 2026-05-31] and is
        # also within the YTD window [2026-01-01, 2026-05-31] -> appears in both columns.
        _seed_one_sale(date(2026, 5, 10), code='BEV')
        # FOOD: sale falls in April, which is inside the YTD window but OUTSIDE the MTD
        # window -> this category's row must still appear (via the `meta` cross-period
        # lookup keyed on category_id from EITHER column), with mtd == 0.0 and ytd > 0.
        _seed_second_sale(date(2026, 4, 15), code='FOOD')

        # NOTE: the symmetric "only in MTD, not YTD" case is structurally unreachable --
        # the MTD window always starts on/after the YTD window's start for the same
        # as_of (mtd_start >= ytd_start), so the MTD window is always a subset of the
        # YTD window; nothing counted in MTD can fall outside YTD. Not tested here.

        out = build_sales_by_product_line(date(2026, 5, 31), date(2026, 5, 1), date(2026, 1, 1))
        assert len(out['rows']) == 2
        rows_by_code = {r['code']: r for r in out['rows']}
        assert set(rows_by_code) == {'BEV', 'FOOD'}

        food = rows_by_code['FOOD']
        assert food['mtd'] == 0.0
        assert food['ytd'] > 0.0
        assert food['name'] == 'FOOD'

        bev = rows_by_code['BEV']
        assert bev['mtd'] > 0.0
        assert bev['ytd'] > 0.0
        assert bev['name'] == 'BEV'
