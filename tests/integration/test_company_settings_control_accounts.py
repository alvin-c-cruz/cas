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
