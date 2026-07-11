from app.accounts.models import Account
from app.settings import AppSettings
from app.audit.models import AuditLog


def _acct(db_session, code, name, atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb, parent_id=None)
    db_session.add(a); db_session.commit()
    return a


def _leaf(db_session, parent, code, name, atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb, parent_id=parent.id)
    db_session.add(a); db_session.commit()
    return a


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True


class TestControlAccountsSettings:
    def test_get_renders_for_accountant(self, client, db_session, accountant_user):
        _login(client, accountant_user)
        r = client.get('/settings/control-accounts')
        assert r.status_code == 200
        assert b'Control Accounts' in r.data

    def test_non_accountant_blocked(self, client, db_session, staff_user):
        _login(client, staff_user)
        r = client.get('/settings/control-accounts', follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_save_assigns_and_audits(self, client, db_session, accountant_user):
        parent = _acct(db_session, '1200', 'Receivables', 'Asset', 'Debit')
        ar = _leaf(db_session, parent, '1210', 'AR - Trade')
        _login(client, accountant_user)
        r = client.post('/settings/control-accounts', data={
            'ar_trade_account_code': '1210',
            'ap_trade_account_code': '',
            'creditable_wht_account_code': '',
            'wht_payable_account_code': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert AppSettings.get_setting('ar_trade_account_code') == '1210'
        assert AuditLog.query.filter_by(module='control_accounts').count() >= 1

    def test_save_rejects_unknown_code(self, client, db_session, accountant_user):
        _login(client, accountant_user)
        r = client.post('/settings/control-accounts', data={
            'ar_trade_account_code': '9999',
            'ap_trade_account_code': '', 'creditable_wht_account_code': '',
            'wht_payable_account_code': '',
        }, follow_redirects=True)
        assert AppSettings.get_setting('ar_trade_account_code') in (None, '')

    def test_save_rejects_group_header(self, client, db_session, accountant_user):
        parent = _acct(db_session, '1200', 'Receivables', 'Asset', 'Debit')
        _leaf(db_session, parent, '1210', 'AR - Trade')  # makes 1200 a parent
        _login(client, accountant_user)
        r = client.post('/settings/control-accounts', data={
            'ar_trade_account_code': '1200',  # group header -> not postable
            'ap_trade_account_code': '', 'creditable_wht_account_code': '',
            'wht_payable_account_code': '',
        }, follow_redirects=True)
        assert AppSettings.get_setting('ar_trade_account_code') in (None, '')
