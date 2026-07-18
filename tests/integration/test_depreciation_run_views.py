from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.fixed_asset_depreciation.models import DepreciationRun
from app.fixed_assets.models import FixedAsset
from tests.integration.test_depreciation_post_run import _asset

pytestmark = [pytest.mark.integration]


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
