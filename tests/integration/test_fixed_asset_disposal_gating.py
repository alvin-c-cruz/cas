import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_routes_404_when_module_off(client, db_session, main_branch, admin_user, login_user):
    AppSettings.set_setting('module_enabled:fixed_asset_disposal', '0')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-asset-disposal')
    assert resp.status_code == 404


def test_routes_available_when_module_on(client, db_session, main_branch, admin_user, login_user):
    AppSettings.set_setting('module_enabled:fixed_asset_disposal', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-asset-disposal')
    assert resp.status_code == 200


def test_sidebar_area_shows_disposal_entry_when_enabled(client, db_session, main_branch,
                                                         admin_user, login_user):
    """Regression guard for the exact gap Slice 2's Task 8 found the hard way: enabling
    a module whose route/icon isn't in base.html's _nav_ep/_nav_icon dicts 500s the
    dashboard instead of just being invisible."""
    AppSettings.set_setting('module_enabled:fixed_asset_disposal', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/dashboard')
    assert resp.status_code == 200


def test_cannot_toggle_on_without_prerequisites_enabled(db_session):
    """depends_on: ['fixed_assets', 'fixed_asset_depreciation'] is enforced by can_toggle()
    at the settings-page level (see Slice 2's own gating test for why NOT
    module_enabled() at runtime)."""
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('fixed_asset_disposal', enable=True, enabled_keys=['fixed_assets'])
    assert ok is False
    assert 'fixed_asset_depreciation' in reason

    ok2, reason2 = can_toggle('fixed_asset_disposal', enable=True,
                              enabled_keys=['fixed_assets', 'fixed_asset_depreciation'])
    assert ok2 is True
