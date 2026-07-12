import pytest
from app import db
from app.accounts.models import Account
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_accountant_can_view_and_save_control_accounts(client, db_session, accountant_user):
    # get_postable_accounts() excludes top-level/group-header accounts (no
    # parent_id) -- create a parent so the leaf under test is postable.
    parent = Account(code='CSCA00', name='Assets Group', account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db.session.add(parent); db.session.commit()
    acct = Account(code='CSCA01', name='AR Trade Test', account_type='Asset',
                   normal_balance='Debit', is_active=True, parent_id=parent.id)
    db.session.add(acct); db.session.commit()

    login(client, 'accountant', 'accountant123')
    resp = client.get('/settings/control-accounts')
    assert resp.status_code == 200

    resp = client.post('/settings/control-accounts', data={
        'ar_trade_account_code': acct.code,
        'ap_trade_account_code': '', 'creditable_wht_account_code': '', 'wht_payable_account_code': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('ar_trade_account_code') == acct.code


def test_staff_cannot_view_control_accounts(client, db_session, staff_user, main_branch):
    staff_user.add_branch(main_branch)
    login(client, 'staff', 'staff123')
    resp = client.get('/settings/control-accounts', follow_redirects=True)
    assert b'Only Accountants and Administrators' in resp.data or resp.status_code in (302, 403)


def test_control_accounts_url_resolves_to_new_blueprint(app):
    """Verify that /settings/control-accounts resolves to the NEW company_settings
    blueprint endpoints, not the OLD control_accounts blueprint endpoints.

    This test pins the fact that company_settings_bp must be registered BEFORE
    control_accounts_bp in app/__init__.py (line 294 vs 299), so Werkzeug routes
    the URL to the new endpoints. If registration order is ever swapped, this test
    will catch it."""
    with app.app_context():
        adapter = app.url_map.bind('localhost')

        # GET should resolve to company_settings.control_accounts
        endpoint, _ = adapter.match('/settings/control-accounts', method='GET')
        assert endpoint == 'company_settings.control_accounts'

        # POST should resolve to company_settings.save_control_accounts
        endpoint, _ = adapter.match('/settings/control-accounts', method='POST')
        assert endpoint == 'company_settings.save_control_accounts'
