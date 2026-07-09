import pytest

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


def _enable(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def test_dr_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    """A disabled optional module is made to look ABSENT, not forbidden: the
    before_request gate in create_app calls abort(404)."""
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/delivery-receipts', follow_redirects=False)
    assert resp.status_code == 404          # gated off by default


def test_dr_registry_entry_is_optional_so_gated_per_user(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'delivery_receipts')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == ['sales_orders']
    assert 'delivery_receipts' in all_permission_keys()   # per_user keeps it in the grid


def test_dr_list_ok_when_enabled(client, db_session, admin_user, main_branch):
    _enable(db_session, 'delivery_receipts')
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/delivery-receipts').status_code == 200
