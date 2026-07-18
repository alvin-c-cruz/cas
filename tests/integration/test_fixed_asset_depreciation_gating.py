import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_routes_404_when_module_off(client, db_session, main_branch, admin_user, login_user):
    AppSettings.set_setting('module_enabled:fixed_asset_depreciation', '0')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-asset-depreciation')
    assert resp.status_code == 404


def test_routes_available_when_module_on(client, db_session, main_branch, admin_user, login_user):
    AppSettings.set_setting('module_enabled:fixed_asset_depreciation', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-asset-depreciation')
    assert resp.status_code == 200


def test_cannot_toggle_on_without_fixed_assets_enabled_first(db_session):
    """depends_on: ['fixed_assets'] is enforced by can_toggle() at the settings-page
    level (NOT by module_enabled() at runtime -- that only checks the module's own
    AppSettings row). An admin cannot flip fixed_asset_depreciation ON while
    fixed_assets itself is not among the currently-enabled keys."""
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('fixed_asset_depreciation', enable=True, enabled_keys=[])
    assert ok is False
    assert 'fixed_assets' in reason

    ok2, reason2 = can_toggle('fixed_asset_depreciation', enable=True,
                              enabled_keys=['fixed_assets'])
    assert ok2 is True
