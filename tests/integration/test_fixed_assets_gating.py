"""Task 12: module registration + gating for the Fixed Asset Register.

fixed_assets is optional, default_enabled=False, and (deliberately, per the plan) NOT
per_user -- so it is instance-gated only, same shape as product_categories/bir_reports.
Mirrors test_vat_settlement_module_gating.py / test_product_categories_crud.py's pattern:
admin_user (bypasses book_permissions via has_full_access) + clear_module_config_cache()
after every AppSettings.set_setting('module_enabled:...') since get_module_override is
memoized for 1h and won't see the write otherwise.
"""
import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_fixed_assets_routes_404_when_module_off(client, db_session, main_branch, admin_user,
                                                  login_user):
    AppSettings.set_setting('module_enabled:fixed_assets', '0')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-assets')
    assert resp.status_code == 404


def test_fixed_assets_routes_available_when_module_on(client, db_session, main_branch, admin_user,
                                                       login_user):
    AppSettings.set_setting('module_enabled:fixed_assets', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/fixed-assets')
    assert resp.status_code == 200


def test_fixed_assets_area_appears_in_sidebar(client, db_session, main_branch, admin_user,
                                              login_user):
    AppSettings.set_setting('module_enabled:fixed_assets', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/dashboard')
    assert b'Fixed Assets' in resp.data
