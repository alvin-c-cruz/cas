"""budgeting is optional, default_enabled=False, NOT per_user -- instance-gated only,
same shape as fixed_assets/bir_reports. Mirrors test_fixed_assets_gating.py.
"""
import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def test_budgeting_routes_404_when_module_off(client, db_session, main_branch, admin_user,
                                               login_user):
    AppSettings.set_setting('module_enabled:budgeting', '0')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/budgeting')
    assert resp.status_code == 404


def test_budgeting_routes_available_when_module_on(client, db_session, main_branch, admin_user,
                                                    login_user):
    AppSettings.set_setting('module_enabled:budgeting', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/budgeting')
    assert resp.status_code == 200


def test_budgeting_area_appears_in_sidebar(client, db_session, main_branch, admin_user,
                                           login_user):
    AppSettings.set_setting('module_enabled:budgeting', '1')
    db_session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/dashboard')
    assert b'Budget Entry' in resp.data
