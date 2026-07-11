import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


def _enable(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def test_po_registry_entry_shape(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'purchase_orders')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == ['products']
    assert e['area'] == 'Purchases' and e['endpoints'] == ('purchase_orders.',)
    assert 'purchase_orders' in all_permission_keys()


def test_po_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/purchase-orders', follow_redirects=False).status_code == 404


def test_po_list_ok_when_enabled(client, db_session, admin_user, main_branch):
    _enable(db_session, 'products', 'purchase_orders')
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/purchase-orders').status_code == 200
