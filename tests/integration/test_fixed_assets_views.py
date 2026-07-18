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


from decimal import Decimal
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem


def test_tag_ap_line_as_fixed_asset(client, db_session, accountant_user, main_branch, login_user):
    _ensure_list_endpoint(client.application)
    cost, accum, exp = _accounts(db_session)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-2026-01-0002',
                         ap_date=date(2026, 1, 20), due_date=date(2026, 2, 20),
                         vendor_name='Office Depot', status='posted')
    db_session.add(ap)
    db_session.flush()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Standing Desk',
                               amount=Decimal('15000.00'), line_total=Decimal('15000.00'),
                               account_id=cost.id)
    db_session.add(item)
    db_session.commit()

    login_user(client, 'accountant', 'accountant123')
    resp = client.post(f'/fixed-assets/tag/ap_bill/{ap.id}/{item.id}', data={
        'code': 'FA-0002', 'name': 'Standing Desk', 'branch_id': str(main_branch.id),
        'category_id': '', 'acquisition_date': '2026-01-20', 'acquisition_cost': '15000.00',
        'cost_account_id': str(cost.id), 'opening_accumulated_depreciation': '0',
        'accumulated_depreciation_account_id': str(accum.id),
        'depreciation_expense_account_id': str(exp.id),
        'depreciation_method': 'straight_line', 'useful_life_months': '36',
        'declining_balance_rate': '', 'total_estimated_units': '', 'salvage_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    asset = FixedAsset.query.filter_by(code='FA-0002').first()
    assert asset is not None
    assert asset.acquisition_source_type == 'ap_bill'
    assert asset.acquisition_source_id == ap.id
    assert asset.acquisition_source_line_id == item.id
    assert asset.acquisition_cost == Decimal('15000.00')
    assert asset.cost_account_id == cost.id

    log = AuditLog.query.filter_by(module='fixed_assets', action='create',
                                    record_id=asset.id).first()
    assert log is not None


def test_tag_draft_ap_line_rejected(client, db_session, accountant_user, main_branch, login_user):
    cost, accum, exp = _accounts(db_session)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-2026-01-0003',
                         ap_date=date(2026, 1, 20), due_date=date(2026, 2, 20),
                         vendor_name='Office Depot', status='draft')
    db_session.add(ap)
    db_session.flush()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Chair',
                               amount=Decimal('5000.00'), line_total=Decimal('5000.00'),
                               account_id=cost.id)
    db_session.add(item)
    db_session.commit()

    login_user(client, 'accountant', 'accountant123')
    # Set a realistic Referer (the AP bill's own detail page, where a "Tag as
    # Fixed Asset" action link would live) so the error-path redirect lands on
    # a real page that renders flashed messages via base.html -- redirecting to
    # fixed_assets.list would hit this test module's route stub (Task 8 isn't
    # built yet), which renders no template and therefore no flash message.
    resp = client.get(f'/fixed-assets/tag/ap_bill/{ap.id}/{item.id}', follow_redirects=True,
                      headers={'Referer': f'/accounts-payable/{ap.id}'})
    assert FixedAsset.query.count() == 0
    assert b'posted' in resp.data.lower()


def _create_asset(db_session, main_branch, cost, accum, exp, code='FA-0009',
                  source_type='opening', source_id=None, source_line_id=None):
    from app.fixed_assets.services import create_fixed_asset
    return create_fixed_asset(
        branch_id=main_branch.id, code=code, name='Test Asset', category_id=None,
        acquisition_source_type=source_type, acquisition_source_id=source_id,
        acquisition_source_line_id=source_line_id, acquisition_date=date(2024, 1, 1),
        acquisition_cost=Decimal('10000'), cost_account_id=cost.id,
        accumulated_depreciation_account_id=accum.id, depreciation_expense_account_id=exp.id,
        depreciation_method='straight_line', useful_life_months=36, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=Decimal('0'), created_by_id=1,
    )


def test_list_and_view(client, db_session, accountant_user, main_branch, login_user):
    cost, accum, exp = _accounts(db_session)
    asset = _create_asset(db_session, main_branch, cost, accum, exp)
    login_user(client, 'accountant', 'accountant123')

    resp = client.get('/fixed-assets')
    assert resp.status_code == 200
    assert b'FA-0009' in resp.data

    resp = client.get(f'/fixed-assets/{asset.id}')
    assert resp.status_code == 200
    assert b'Test Asset' in resp.data


def test_edit_asset(client, db_session, accountant_user, main_branch, login_user):
    cost, accum, exp = _accounts(db_session)
    asset = _create_asset(db_session, main_branch, cost, accum, exp)
    login_user(client, 'accountant', 'accountant123')

    resp = client.post(f'/fixed-assets/{asset.id}/edit', data={
        'code': asset.code, 'name': 'Renamed Asset', 'branch_id': str(main_branch.id),
        'category_id': '', 'acquisition_date': '2024-01-01', 'acquisition_cost': '10000',
        'cost_account_id': str(cost.id), 'opening_accumulated_depreciation': '0',
        'accumulated_depreciation_account_id': str(accum.id),
        'depreciation_expense_account_id': str(exp.id),
        'depreciation_method': 'straight_line', 'useful_life_months': '48',
        'declining_balance_rate': '', 'total_estimated_units': '', 'salvage_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(asset)
    assert asset.name == 'Renamed Asset'
    assert asset.useful_life_months == 48

    log = AuditLog.query.filter_by(module='fixed_assets', action='update',
                                    record_id=asset.id).first()
    assert log is not None


def test_edit_cannot_change_cost_account(client, db_session, accountant_user, main_branch,
                                          login_user):
    """cost_account_id is immutable -- posting a different value must be ignored."""
    cost, accum, exp = _accounts(db_session)
    other_cost = Account(code='17303', name='Machinery - Cost', account_type='Asset',
                         normal_balance='Debit')
    db_session.add(other_cost)
    db_session.commit()
    asset = _create_asset(db_session, main_branch, cost, accum, exp)
    login_user(client, 'accountant', 'accountant123')

    client.post(f'/fixed-assets/{asset.id}/edit', data={
        'code': asset.code, 'name': asset.name, 'branch_id': str(main_branch.id),
        'category_id': '', 'acquisition_date': '2024-01-01', 'acquisition_cost': '10000',
        'cost_account_id': str(other_cost.id), 'opening_accumulated_depreciation': '0',
        'accumulated_depreciation_account_id': str(accum.id),
        'depreciation_expense_account_id': str(exp.id),
        'depreciation_method': 'straight_line', 'useful_life_months': '36',
        'declining_balance_rate': '', 'total_estimated_units': '', 'salvage_value': '0',
    }, follow_redirects=True)
    db_session.refresh(asset)
    assert asset.cost_account_id == cost.id  # unchanged


def test_delete_asset_frees_tag(client, db_session, accountant_user, main_branch, login_user):
    cost, accum, exp = _accounts(db_session)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-2026-01-0004',
                         ap_date=date(2026, 1, 5), due_date=date(2026, 2, 5),
                         vendor_name='Vendor X', status='posted')
    db_session.add(ap)
    db_session.flush()
    item = AccountsPayableItem(ap_id=ap.id, line_number=1, description='Printer',
                               amount=Decimal('8000'), line_total=Decimal('8000'),
                               account_id=cost.id)
    db_session.add(item)
    db_session.commit()
    asset = _create_asset(db_session, main_branch, cost, accum, exp, code='FA-0010',
                          source_type='ap_bill', source_id=ap.id, source_line_id=item.id)

    login_user(client, 'accountant', 'accountant123')
    asset_id = asset.id
    resp = client.post(f'/fixed-assets/{asset.id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    assert FixedAsset.query.filter_by(code='FA-0010').first() is None

    from app.fixed_assets.services import get_tag_for_line
    assert get_tag_for_line('ap_bill', ap.id, item.id) is None

    log = AuditLog.query.filter_by(module='fixed_assets', action='delete',
                                    record_id=asset_id).first()
    assert log is not None


def test_detail_page_renders_single_csrf_token_in_delete_form(client, db_session, accountant_user,
                                                               main_branch, login_user):
    cost, accum, exp = _accounts(db_session)
    asset = _create_asset(db_session, main_branch, cost, accum, exp, code='FA-0011')
    login_user(client, 'accountant', 'accountant123')
    resp = client.get(f'/fixed-assets/{asset.id}')
    assert resp.data.count(b'name="csrf_token"') == 1
