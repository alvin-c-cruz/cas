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


def _set_module(key, enabled):
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting(f'module_enabled:{key}', '1' if enabled else '0')
    clear_module_config_cache()


class TestAbnormalLossFieldIsActuallyRendered:
    """R-07 P6 Task 4, rendered rather than merely registered.

    The registry test asserts `visible_control_accounts()` returns the key. That is
    NOT the same claim as the accountant being able to assign the account, and the
    difference is exactly how the P4 labor_applied deadlock shipped: every unit test
    set control accounts directly, nothing rendered this page, and a field the close
    path demanded was invisible on the only install that could reach it. Task 5 makes
    close_run demand `abnormal_loss` the same way, so the same gap is available again
    and gets a render assertion this time.
    """

    def test_the_field_renders_on_a_process_only_install(
            self, client, db_session, accountant_user):
        _set_module('work_orders', False)
        _set_module('production_runs', True)
        _login(client, accountant_user)
        r = client.get('/settings/control-accounts')
        assert r.status_code == 200
        assert b'abnormal_loss_account_code' in r.data, \
            'the input must exist, or the account can never be assigned'
        assert b'Abnormal Loss' in r.data, 'and it must be labelled for a human'

    def test_the_field_is_absent_on_a_discrete_only_install(
            self, client, db_session, accountant_user):
        """The complement, so the test above cannot pass by the field simply always
        being there. A discrete-only install never posts abnormal loss."""
        _set_module('work_orders', True)
        _set_module('production_runs', False)
        _login(client, accountant_user)
        r = client.get('/settings/control-accounts')
        assert r.status_code == 200
        assert b'abnormal_loss_account_code' not in r.data
        assert b'labor_applied_account_code' in r.data, \
            'the contrast: the discrete track DOES post labor, so that field stays'
