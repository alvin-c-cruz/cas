"""Integration tests for the Fixed Asset register views (R-05 Slice 1)."""
from datetime import date

import pytest

from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _accounts(db_session):
    # normal_balance is NOT NULL on Account -- the brief's fixture omitted it;
    # Asset and Expense accounts are both normally Debit-balance.
    cost = Account(code='17301', name='Office Equipment - Cost', account_type='Asset',
                   normal_balance='Debit')
    accum = Account(code='17302', name='Office Equipment - Accum. Dep.', account_type='Asset',
                    normal_balance='Debit')
    exp = Account(code='60501', name='Depreciation Expense', account_type='Expense',
                 normal_balance='Debit')
    db_session.add_all([cost, accum, exp])
    db_session.commit()
    return cost, accum, exp


def _ensure_list_endpoint(app):
    """form.html's Cancel link and the opening-asset view's success redirect
    both call url_for('fixed_assets.list') -- the real route is only wired up
    by Task 8 (list/detail/edit/delete views), not yet built on this branch.
    Stub the endpoint so this integration test of Task 6's own view doesn't
    depend on a route from a different, not-yet-implemented task. Mirrors the
    identical technique already used in
    tests/integration/test_fixed_asset_form_render.py::_ensure_list_endpoint."""
    if 'fixed_assets.list' not in app.view_functions:
        app.add_url_rule('/fixed-assets', endpoint='fixed_assets.list', view_func=lambda: '')


def test_create_opening_asset(client, db_session, accountant_user, main_branch, login_user):
    _ensure_list_endpoint(client.application)
    cost, accum, exp = _accounts(db_session)
    login_user(client, 'accountant', 'accountant123')
    resp = client.post('/fixed-assets/new-opening', data={
        'code': 'FA-0001', 'name': 'Delivery Van', 'branch_id': str(main_branch.id),
        'category_id': '', 'acquisition_date': '2022-03-01', 'acquisition_cost': '800000.00',
        'cost_account_id': str(cost.id), 'opening_accumulated_depreciation': '300000.00',
        'accumulated_depreciation_account_id': str(accum.id),
        'depreciation_expense_account_id': str(exp.id),
        'depreciation_method': 'straight_line', 'useful_life_months': '60',
        'declining_balance_rate': '', 'total_estimated_units': '', 'salvage_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    asset = FixedAsset.query.filter_by(code='FA-0001').first()
    assert asset is not None
    assert asset.acquisition_source_type == 'opening'
    assert asset.acquisition_source_id is None
    assert asset.opening_accumulated_depreciation == 300000
    assert asset.cost_account_id == cost.id

    log = AuditLog.query.filter_by(module='fixed_assets', action='create',
                                    record_id=asset.id).first()
    assert log is not None
