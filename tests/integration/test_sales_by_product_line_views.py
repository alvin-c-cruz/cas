"""Integration tests for the Sales by Product Line report routes."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem

D = lambda v: Decimal(str(v))


@pytest.fixture
def sales_by_product_line_module_enabled(db_session):
    """Enable the optional sales_by_product_line report module for the test.

    Mirrors test_product_category_tagging.py::products_module_enabled -- the module
    is default_enabled=False (optional), so the before_request gate 404s the routes
    unless a setting flips it on for this test's duration.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_by_product_line', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user):
    """Session-based login (mirrors test_income_statement_views.py::_login)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _seed(branch_id, when=date(2026, 5, 10)):
    cust = Customer(code='C1', name='Acme'); db.session.add(cust); db.session.flush()
    cat = ProductCategory(code='BEV', name='Beverages', is_active=True)
    db.session.add(cat); db.session.flush()
    p = Product(code='P', name='Cola', category_id=cat.id); db.session.add(p); db.session.flush()
    inv = SalesInvoice(invoice_number='SI-1', invoice_date=when, due_date=when,
                       customer_id=cust.id, customer_name='Acme', status='posted',
                       branch_id=branch_id)
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='x',
                                    product_id=p.id, line_total=D(112), vat_amount=D(12)))
    db.session.commit()


@pytest.mark.integration
class TestSalesByProductLineViews:
    def test_screen_renders_with_category(self, client, db_session, main_branch, admin_user,
                                           sales_by_product_line_module_enabled):
        _login(client, admin_user)
        _select_branch(client, main_branch.id)
        _seed(main_branch.id)
        resp = client.get('/reports/sales-by-product-line?as_of=2026-05-31')
        assert resp.status_code == 200
        assert b'Beverages' in resp.data
        assert b'Total Net Sales' in resp.data
        # No JE was posted for the seeded invoice, so IS net_sales (GL-derived) is 0
        # while the product-line total is not -> variance branch renders.
        assert b'Variance vs Income Statement Net Sales' in resp.data
        assert b'may reflect revenue on manual journal entries' in resp.data

    def test_print_renders(self, client, db_session, main_branch, admin_user,
                            sales_by_product_line_module_enabled):
        _login(client, admin_user)
        _select_branch(client, main_branch.id)
        _seed(main_branch.id)
        resp = client.get('/reports/sales-by-product-line/print?as_of=2026-05-31')
        assert resp.status_code == 200
        assert b'Beverages' in resp.data

    def test_excel_export_content_type(self, client, db_session, main_branch, admin_user,
                                        sales_by_product_line_module_enabled):
        _login(client, admin_user)
        _select_branch(client, main_branch.id)
        _seed(main_branch.id)
        resp = client.get('/reports/sales-by-product-line/export/excel?as_of=2026-05-31')
        assert resp.status_code == 200
        assert 'spreadsheet' in resp.headers['Content-Type']

    def test_404_when_module_disabled(self, client, db_session, main_branch, admin_user):
        """Mirrors test_vat_settlement_module_gating.py::test_404_when_bir_reports_disabled --
        do NOT use the sales_by_product_line_module_enabled fixture; explicitly disable
        instead so the before_request module gate 404s the route."""
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        AppSettings.set_setting('module_enabled:sales_by_product_line', '0')
        db.session.commit()
        clear_module_config_cache()
        _login(client, admin_user)
        _select_branch(client, main_branch.id)
        resp = client.get('/reports/sales-by-product-line')
        assert resp.status_code == 404
