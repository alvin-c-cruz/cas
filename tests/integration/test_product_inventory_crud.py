"""Integration tests for the R-03 slice 1 inventory fields on the Product form."""
import pytest
from decimal import Decimal
from app import db
from app.products.models import Product
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def products_and_inventory_enabled(db_session):
    """Enable both products and inventory for the duration of the test."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    AppSettings.set_setting('module_enabled:inventory', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def test_create_product_with_inventory_tracking_persists(client, db_session, admin_user,
                                                          main_branch, products_and_inventory_enabled):
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'TRK-1', 'name': 'Tracked Widget', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'category_id': '', 'is_active': '1',
                             'track_inventory': 'y', 'costing_method': 'moving_average',
                             'standard_cost': '150.00', 'reorder_level': '20.00'},
                       follow_redirects=True)
    assert resp.status_code == 200
    p = Product.query.filter_by(code='TRK-1').first()
    assert p is not None
    assert p.track_inventory is True
    assert p.costing_method == 'moving_average'
    assert p.standard_cost == Decimal('150.00')
    assert p.reorder_level == Decimal('20.00')
    audit = AuditLog.query.filter_by(module='products', action='create').order_by(
        AuditLog.id.desc()).first()
    assert audit is not None
    assert 'moving_average' in (audit.new_values or '')


def test_create_product_without_tracking_defaults_false(client, db_session, admin_user,
                                                         main_branch, products_and_inventory_enabled):
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'UNTRK-1', 'name': 'Untracked Widget', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'category_id': '', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    p = Product.query.filter_by(code='UNTRK-1').first()
    assert p is not None
    assert p.track_inventory is False
    assert p.costing_method is None


def test_create_product_tracking_without_cost_fields_rejected(client, db_session, admin_user,
                                                               main_branch, products_and_inventory_enabled):
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'BAD-1', 'name': 'Bad Widget', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'category_id': '', 'is_active': '1',
                             'track_inventory': 'y'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert Product.query.filter_by(code='BAD-1').first() is None


def test_edit_product_updates_inventory_fields(client, db_session, admin_user, main_branch,
                                               products_and_inventory_enabled):
    p = Product(code='EDIT-INV', name='Editable', is_active=True)
    db.session.add(p)
    db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post(f'/products/{p.id}/edit',
                       data={'code': 'EDIT-INV', 'name': 'Editable', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'category_id': '', 'is_active': '1',
                             'track_inventory': 'y', 'costing_method': 'fifo',
                             'standard_cost': '75.00', 'reorder_level': '10.00'},
                       follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db.session.get(Product, p.id)
    assert refreshed.track_inventory is True
    assert refreshed.costing_method == 'fifo'
    assert refreshed.standard_cost == Decimal('75.00')
    audit = AuditLog.query.filter_by(module='products', action='update').order_by(
        AuditLog.id.desc()).first()
    assert audit is not None
    assert 'fifo' in (audit.new_values or '')
