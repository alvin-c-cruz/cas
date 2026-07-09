"""Sales Memos: optional-module gating + shared settings account assignment."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.credit_memos]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


def _enable(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def _acct(db_session, code, name, atype, nb):
    from app.accounts.models import Account
    a = Account(code=code, name=name, account_type=atype,
                classification='General', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def test_credit_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    """Disabled optional module looks ABSENT (before_request abort(404))."""
    # Clear any module-config memo leaked by a sibling test that enabled credit_memos
    # (db tables reset per test, but the 1h-memoized override does not).
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/credit-memos').status_code == 404


def test_credit_memos_registry_entry_is_optional_per_user(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'credit_memos')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == []
    assert 'credit_memos' in all_permission_keys()   # per_user keeps it in the grid


def test_credit_list_ok_when_enabled(client, db_session, admin_user, main_branch):
    _enable(db_session, 'credit_memos')
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/credit-memos').status_code == 200


def test_settings_save_persists_and_audits(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.audit.models import AuditLog
    _acct(db_session, '40103', 'Sales Returns and Allowances', 'Income', 'Debit')
    _acct(db_session, '20301', 'Customer Credits', 'Liability', 'Credit')
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.post('/sales-memos/settings/accounts', data={
        'sales_returns_allowances_account_code': '40103',
        'customer_credits_advances_account_code': '20301'}, follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('sales_returns_allowances_account_code') == '40103'
    assert AppSettings.get_setting('customer_credits_advances_account_code') == '20301'
    assert AuditLog.query.filter_by(module='sales_memos', action='assign_accounts').first() is not None


def test_settings_save_rejects_unknown_code(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/sales-memos/settings/accounts', data={
        'sales_returns_allowances_account_code': '99999',
        'customer_credits_advances_account_code': ''}, follow_redirects=True)
    assert AppSettings.get_setting('sales_returns_allowances_account_code') in (None, '')
