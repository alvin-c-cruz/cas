from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.fixed_asset_depreciation.models import DepreciationRun
from app.fixed_assets.models import FixedAsset
from tests.integration.test_depreciation_post_run import _asset

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _fixed_asset_depreciation_module_enabled(db_session, accountant_user):
    """Task 8 gated fixed_asset_depreciation (optional, default_enabled=False, not
    per_user) behind app.__init__'s before_request module-access hook. These Task 7
    tests predate that gate and log in as accountant_user -- mirror the same pattern
    Slice 1's Task 12 used (test_fixed_assets_views.py's _fixed_assets_module_enabled):
    turn the module on at the instance level AND grant this accountant the book
    permission directly (module_enabled alone isn't enough: can_access_module still
    checks book_permissions for a non-full-access role)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:fixed_asset_depreciation', '1')
    db_session.commit()
    clear_module_config_cache()
    perms = accountant_user.get_book_permissions()
    perms['fixed_asset_depreciation'] = True
    accountant_user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


def test_new_run_get_shows_branch_period_picker(client, db_session, accountant_user,
                                                  main_branch, login_user):
    login_user(client, 'accountant', 'accountant123')
    resp = client.get('/fixed-asset-depreciation/new')
    assert resp.status_code == 200
    assert b'branch_id' in resp.data


def test_new_run_post_without_confirm_shows_preview(db_session, main_branch, accountant_user,
                                                     client, login_user):
    _asset(db_session, main_branch)
    login_user(client, 'accountant', 'accountant123')
    resp = client.post('/fixed-asset-depreciation/new', data={
        'branch_id': str(main_branch.id), 'period_year': '2026', 'period_month': '6',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'1000.00' in resp.data or b'1,000.00' in resp.data
    assert DepreciationRun.query.count() == 0  # nothing posted yet


def test_new_run_post_with_confirm_posts_the_run(db_session, main_branch, accountant_user,
                                                  client, login_user):
    _asset(db_session, main_branch)
    login_user(client, 'accountant', 'accountant123')
    client.post('/fixed-asset-depreciation/new', data={
        'branch_id': str(main_branch.id), 'period_year': '2026', 'period_month': '6',
        'confirmed': '1',
    }, follow_redirects=True)
    assert DepreciationRun.query.count() == 1
    assert DepreciationRun.query.first().status == 'posted'


def test_list_shows_posted_runs_with_reverse_action(db_session, main_branch, accountant_user,
                                                     client, login_user):
    _asset(db_session, main_branch)
    login_user(client, 'accountant', 'accountant123')
    client.post('/fixed-asset-depreciation/new', data={
        'branch_id': str(main_branch.id), 'period_year': '2026', 'period_month': '6',
        'confirmed': '1',
    })
    resp = client.get('/fixed-asset-depreciation')
    assert resp.status_code == 200
    assert b'2026-06' in resp.data or b'June 2026' in resp.data


def test_reverse_action_flips_run_status(db_session, main_branch, accountant_user, client,
                                         login_user):
    _asset(db_session, main_branch)
    login_user(client, 'accountant', 'accountant123')
    client.post('/fixed-asset-depreciation/new', data={
        'branch_id': str(main_branch.id), 'period_year': '2026', 'period_month': '6',
        'confirmed': '1',
    })
    run = DepreciationRun.query.first()
    resp = client.post(f'/fixed-asset-depreciation/{run.id}/reverse',
                       data={'reversal_date': '2026-06-30'}, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(run)
    assert run.status == 'reversed'
