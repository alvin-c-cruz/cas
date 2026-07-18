"""Integration tests for Products master CRUD blueprint (Task 8)."""
import html as html_mod
import pytest
from decimal import Decimal
from app import db
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    """Log a user in and set a branch in the session (mirrors other integration tests)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def products_module_enabled(db_session):
    """Enable the optional products module for the duration of the test.

    products is default_enabled=False (optional); tests that hit product endpoints
    need it enabled or the before_request hook aborts with 404.  The fixture clears the
    memoize cache on both setup and teardown so the enabled state does not bleed into
    subsequent tests that assert the default-off behaviour.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def test_create_product_persists_and_audits(client, db_session, admin_user, main_branch,
                                            products_module_enabled):
    u = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db.session.add(u)
    db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'WID-1', 'name': 'Widget', 'description': '',
                             'default_unit_of_measure_id': str(u.id),
                             'default_unit_price': '112.00',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    p = Product.query.filter_by(code='WID-1').first()
    assert p is not None and p.name == 'Widget'
    assert p.default_unit_price == Decimal('112.00')
    assert p.default_unit_of_measure_id == u.id
    assert AuditLog.query.filter_by(module='products', action='create').count() >= 1


def test_edit_product_updates(client, db_session, admin_user, main_branch,
                              products_module_enabled):
    p = Product(code='X', name='X1', is_active=True)
    db.session.add(p)
    db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post(f'/products/{p.id}/edit',
                       data={'code': 'X', 'name': 'X2', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '0'},
                       follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db.session.get(Product, p.id)
    assert refreshed.name == 'X2' and refreshed.is_active is False
    assert AuditLog.query.filter_by(module='products', action='update').count() >= 1


def test_list_products_renders(client, db_session, admin_user, main_branch,
                               products_module_enabled):
    _login(client, admin_user, main_branch)
    resp = client.get('/products')
    assert resp.status_code == 200
    assert b'Products' in resp.data


def test_staff_can_create_product(client, db_session, staff_user, main_branch,
                                  products_module_enabled):
    """Owner directive 2026-07-11 (BUG-QUOTE-DELEGATE-ADD-PRODUCT, full parity with
    customers.create): a staff delegate MAY create a product — previously blocked. products.create
    is exempt from the module gate and its role guard now admits staff-or-above, so a quotation
    delegate can inline-add a product without holding the Products module. (Edit stays locked —
    see test_staff_cannot_edit_product; viewer stays blocked — see below.)"""
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'STF-1', 'name': 'Staff Product', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert Product.query.filter_by(code='STF-1').first() is not None


def test_viewer_cannot_create_product(client, db_session, viewer_user, main_branch,
                                      products_module_enabled):
    """The staff-or-above loosening must NOT reach viewer — the role guard still blocks it,
    so the parity change did not over-open master-data creation."""
    viewer_user.set_branches([main_branch])
    db_session.commit()
    _login(client, viewer_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'VWR-1', 'name': 'Viewer Product', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert Product.query.filter_by(code='VWR-1').first() is None


def test_staff_cannot_edit_product(client, db_session, staff_user, main_branch,
                                   products_module_enabled):
    """Staff users must be blocked from editing products (module-level gate on edit view)."""
    p = Product(code='EDIT-ME', name='Editable', is_active=True)
    db.session.add(p)
    db.session.commit()
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post(f'/products/{p.id}/edit',
                       data={'code': 'EDIT-ME', 'name': 'Should Not Change', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db.session.get(Product, p.id)
    assert refreshed.name == 'Editable'  # unchanged
    text = html_mod.unescape(resp.data.decode())
    assert 'do not have access to this module' in text.lower()


def test_ajax_create_product_returns_json(client, db_session, admin_user, main_branch,
                                          products_module_enabled):
    """AJAX POST to /products/create returns JSON with ok=True and product data."""
    u = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db.session.add(u)
    db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'P-AJAX', 'name': 'Ajax Product', 'description': '',
                             'default_unit_of_measure_id': str(u.id),
                             'default_unit_price': '', 'default_account_id': '',
                             'is_active': '1'},
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['product']['code'] == 'P-AJAX'
    assert data['product']['name'] == 'Ajax Product'
    assert Product.query.filter_by(code='P-AJAX').count() == 1


def test_ajax_create_product_validation_error(client, db_session, admin_user, main_branch,
                                              products_module_enabled):
    """AJAX POST to /products/create with missing required fields returns JSON with ok=False."""
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={},  # missing code and name
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['ok'] is False
    assert 'errors' in data
    assert Product.query.count() == 0


def test_create_product_with_job_order_name(client, db_session, admin_user, main_branch,
                                             products_module_enabled):
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'JON-3', 'name': 'Widget C', 'description': '',
                             'job_order_name': 'WGT-C-PROD',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    p = Product.query.filter_by(code='JON-3').first()
    assert p is not None
    assert p.job_order_name == 'WGT-C-PROD'


def test_edit_product_updates_job_order_name(client, db_session, admin_user, main_branch,
                                              products_module_enabled):
    p = Product(code='JON-4', name='Widget D', is_active=True)
    db.session.add(p); db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post(f'/products/{p.id}/edit',
                       data={'code': 'JON-4', 'name': 'Widget D', 'description': '',
                             'job_order_name': 'WGT-D-PROD',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(p)
    assert p.job_order_name == 'WGT-D-PROD'
    audit = AuditLog.query.filter_by(module='products', action='update').order_by(
        AuditLog.id.desc()).first()
    assert audit is not None
    assert 'job_order_name' in (audit.new_values or '')
