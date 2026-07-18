from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.fixed_asset_disposal.models import FixedAssetDisposal
from tests.integration.test_fixed_asset_dispose_service import _asset, _assign_gain_loss_account, \
    _cash_account

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _fixed_asset_disposal_module_enabled(db_session, accountant_user):
    """fixed_asset_disposal is optional, default_enabled=False, not per_user --
    module_enabled alone isn't enough for a non-full-access role; also grant the
    book permission directly. Mirrors Slice 2's test_depreciation_run_views.py
    fixture and Slice 1's test_fixed_assets_views.py precedent."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:fixed_asset_disposal', '1')
    db_session.commit()
    clear_module_config_cache()
    perms = accountant_user.get_book_permissions()
    perms['fixed_asset_disposal'] = True
    accountant_user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


def test_new_disposal_get_shows_form_for_the_asset(client, db_session, accountant_user,
                                                    main_branch, login_user):
    asset, *_ = _asset(db_session, main_branch)
    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/fixed-asset-disposal/new/{asset.id}')
    assert resp.status_code == 200
    assert asset.code.encode() in resp.data


def test_new_disposal_post_creates_disposal_and_redirects(db_session, main_branch,
                                                           accountant_user, client, login_user):
    asset, *_ = _asset(db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
                       opening_accum=Decimal('320000.00'))
    _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)
    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/fixed-asset-disposal/new/{asset.id}', data={
        'disposal_date': '2026-06-30', 'disposal_type': 'sale',
        'proceeds_amount': '600000.00', 'proceeds_account_id': str(cash_acct.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert FixedAssetDisposal.query.count() == 1


def test_scrap_post_does_not_require_proceeds_account(db_session, main_branch, accountant_user,
                                                       client, login_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/fixed-asset-disposal/new/{asset.id}', data={
        'disposal_date': '2026-06-30', 'disposal_type': 'scrap', 'proceeds_amount': '0',
        'proceeds_account_id': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert FixedAssetDisposal.query.filter_by(fixed_asset_id=asset.id).count() == 1


def test_list_shows_disposals_with_void_action(db_session, main_branch, accountant_user, client,
                                               login_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    login_user(client, 'accountant', 'accountant123')
    client.post(f'/fixed-asset-disposal/new/{asset.id}', data={
        'disposal_date': '2026-06-30', 'disposal_type': 'scrap', 'proceeds_amount': '0',
        'proceeds_account_id': '',
    })
    resp = client.get('/fixed-asset-disposal')
    assert resp.status_code == 200
    assert asset.code.encode() in resp.data


def test_void_action_flips_disposal_status(db_session, main_branch, accountant_user, client,
                                           login_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    login_user(client, 'accountant', 'accountant123')
    client.post(f'/fixed-asset-disposal/new/{asset.id}', data={
        'disposal_date': '2026-06-30', 'disposal_type': 'scrap', 'proceeds_amount': '0',
        'proceeds_account_id': '',
    })
    disposal = FixedAssetDisposal.query.first()
    resp = client.post(f'/fixed-asset-disposal/{disposal.id}/void',
                       data={'void_date': '2026-06-30'}, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(disposal)
    assert disposal.status == 'void'
