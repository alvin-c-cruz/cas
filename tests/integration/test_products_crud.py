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


def test_staff_cannot_create_product(client, db_session, staff_user, main_branch,
                                     products_module_enabled):
    """Staff users must be blocked from creating products (module-level gate)."""
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'BLK-1', 'name': 'Blocked Product', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    # No row must have been inserted
    assert Product.query.filter_by(code='BLK-1').first() is None
    # Module-access block flash (before_request gate fires before the view)
    text = html_mod.unescape(resp.data.decode())
    assert 'do not have access to this module' in text.lower()


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
