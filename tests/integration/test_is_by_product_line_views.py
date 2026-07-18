"""Integration tests for the Income Statement by Product Line report routes."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.product_categories.models import ProductCategory
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem

pytestmark = [pytest.mark.integration]

D = lambda v: Decimal(str(v))


@pytest.fixture
def is_by_product_line_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:income_statement_by_product_line', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _seed(branch_id):
    cust = Customer(code='C1', name='Acme'); db.session.add(cust); db.session.flush()
    cat = ProductCategory(code='BEV', name='Beverages', is_active=True)
    db.session.add(cat); db.session.flush()
    p = Product(code='P1', name='Cola', category_id=cat.id, standard_cost=D('5'))
    db.session.add(p); db.session.flush()
    inv = SalesInvoice(invoice_number='SI-1', invoice_date=date(2026, 5, 10),
                       due_date=date(2026, 5, 10), customer_id=cust.id, customer_name='Acme',
                       status='posted', branch_id=branch_id)
    db.session.add(inv); db.session.flush()
    db.session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1, description='Cola',
                                    product_id=p.id, quantity=D('10'),
                                    line_total=D('112'), vat_amount=D('12')))
    db.session.commit()


class TestIncomeStatementByProductLineViews:
    def test_screen_renders(self, client, admin_user, main_branch, login_user,
                            is_by_product_line_module_enabled):
        login_user(client, 'admin', 'admin123')
        _seed(main_branch.id)
        resp = client.get('/reports/income-statement-by-product-line?as_of=2026-05-31')
        assert resp.status_code == 200
        assert b'Beverages' in resp.data

    def test_print_renders(self, client, admin_user, main_branch, login_user,
                           is_by_product_line_module_enabled):
        login_user(client, 'admin', 'admin123')
        _seed(main_branch.id)
        resp = client.get('/reports/income-statement-by-product-line/print?as_of=2026-05-31')
        assert resp.status_code == 200
        assert b'Beverages' in resp.data

    def test_excel_export_content_type(self, client, admin_user, main_branch, login_user,
                                       is_by_product_line_module_enabled):
        login_user(client, 'admin', 'admin123')
        _seed(main_branch.id)
        resp = client.get('/reports/income-statement-by-product-line/export/excel?as_of=2026-05-31')
        assert resp.status_code == 200
        assert 'spreadsheet' in resp.headers['Content-Type']


def test_404_when_module_disabled(client, admin_user, main_branch, login_user):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:income_statement_by_product_line', '0')
    db.session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/reports/income-statement-by-product-line')
    assert resp.status_code == 404
    clear_module_config_cache()
