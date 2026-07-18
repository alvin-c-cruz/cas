"""R-03 slice 1: the 4 inventory fields on the Product form are gated by the
`inventory` module -- absent from the rendered form when off, present when on."""
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def products_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def test_inventory_fields_absent_when_module_off(client, db_session, admin_user, main_branch,
                                                  products_module_enabled):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:inventory', '0')
    db.session.commit()
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.get('/products/create')
    assert resp.status_code == 200
    assert b'name="track_inventory"' not in resp.data
    assert b'name="costing_method"' not in resp.data
    assert b'name="standard_cost"' not in resp.data
    assert b'name="reorder_level"' not in resp.data


def test_inventory_fields_present_when_module_on(client, db_session, admin_user, main_branch,
                                                  products_module_enabled):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:inventory', '1')
    db.session.commit()
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.get('/products/create')
    assert resp.status_code == 200
    assert b'name="track_inventory"' in resp.data
    assert b'name="costing_method"' in resp.data
    assert b'name="standard_cost"' in resp.data
    assert b'name="reorder_level"' in resp.data


def test_inventory_appears_in_settings_packages_table(client, db_session, admin_user, main_branch,
                                                       login_user):
    login_user(client, 'admin', 'admin123')
    resp = client.get('/settings')
    assert resp.status_code == 200
    assert b'Inventory (Item Costing)' in resp.data


def test_track_inventory_validation_error_renders_on_page(client, db_session, admin_user,
                                                           main_branch, products_module_enabled):
    """A validation failure on track_inventory must be visible to the user, not just
    block the save server-side (found via manual browser check: the checkbox is
    rendered outside render_field, which is the only place that normally displays
    field.errors -- an easy spot to silently drop error display when hand-rolling markup)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:inventory', '1')
    db.session.commit()
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.post('/products/create',
                       data={'code': 'GATE-1', 'name': 'Gate Widget', 'description': '',
                             'default_unit_of_measure_id': '', 'default_unit_price': '',
                             'default_account_id': '', 'category_id': '', 'is_active': '1',
                             'track_inventory': 'y'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'required when Track Inventory is checked' in resp.data
