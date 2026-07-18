from datetime import date
import pytest
from tests.unit.test_fixed_asset_schedule_report import _asset_with_category
from decimal import Decimal

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _fixed_asset_depreciation_module_enabled(db_session):
    """Task 8 gated fixed_asset_depreciation -- even admin_user (which bypasses
    per-user book_permissions via has_full_access) still needs the instance-level
    module_enabled setting on, or every route in this blueprint 404s regardless
    of role. Mirrors test_depreciation_run_views.py's own enable fixture."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:fixed_asset_depreciation', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_schedule_report_screen(client, db_session, main_branch, admin_user, login_user):
    _asset_with_category(db_session, main_branch, None, 'FA-SV01', Decimal('12000.00'))
    login_user(client, 'admin', 'admin123')
    resp = client.get(f'/fixed-asset-depreciation/schedule?branch_id={main_branch.id}&as_of=2026-06-30')
    assert resp.status_code == 200
    assert b'FA-SV01' in resp.data


def test_schedule_report_export_excel(client, db_session, main_branch, admin_user, login_user):
    _asset_with_category(db_session, main_branch, None, 'FA-SV02', Decimal('12000.00'))
    login_user(client, 'admin', 'admin123')
    resp = client.get(
        f'/fixed-asset-depreciation/schedule/export?branch_id={main_branch.id}&as_of=2026-06-30')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == \
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
