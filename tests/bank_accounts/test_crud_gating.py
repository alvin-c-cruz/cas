"""Register CRUD + module gating + sidebar visibility tests (R-04 slice 1)."""
import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable_bank_accounts(db_session):
    AppSettings.set_setting('module_enabled:bank_accounts', '1')
    db_session.commit(); clear_module_config_cache()


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.get('/bank-accounts/')
    assert resp.status_code == 404


def test_all_endpoints_404_when_module_off(client, accountant_user, db_session, main_branch, cash_account):
    """Every bank_accounts route -- not just list -- is 404 when the module is off
    (optional-module-gating-traps: a new route isn't hidden unless every one of its
    endpoints is covered). Uses a real BankAccount id for edit/toggle so the 404 is
    provably the module gate firing, not an ambiguous 'record not found'."""
    _login(client, accountant_user, main_branch)

    resp = client.get('/bank-accounts/')
    assert resp.status_code == 404

    resp = client.get('/bank-accounts/new')
    assert resp.status_code == 404
    resp = client.post('/bank-accounts/new', data={'code': 'X', 'name': 'X', 'account_id': cash_account.id})
    assert resp.status_code == 404

    resp = client.post('/bank-accounts/quick-add', data={'code': 'X', 'name': 'X', 'account_id': cash_account.id})
    assert resp.status_code == 404

    # Create a BankAccount directly (bypassing the gated route) so edit/toggle have a
    # real id to target -- the gate must still block them even though the row exists.
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=main_branch.id, code='BA-OFF', name='Off Test',
                      account_id=cash_account.id, account_type='checking',
                      opening_balance=0, created_by='test')
    db_session.add(ba)
    db_session.commit()

    resp = client.get(f'/bank-accounts/{ba.id}/edit')
    assert resp.status_code == 404
    resp = client.post(f'/bank-accounts/{ba.id}/edit', data={'code': 'BA-OFF', 'name': 'Off Test'})
    assert resp.status_code == 404

    resp = client.post(f'/bank-accounts/{ba.id}/toggle-active')
    assert resp.status_code == 404


def test_create_bank_account(client, accountant_user, db_session, main_branch, cash_account):
    _enable_bank_accounts(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/bank-accounts/new', data={
        'code': 'BA-BPI', 'name': 'BPI Main', 'account_id': cash_account.id,
        'bank_name': 'BPI', 'account_number': '1234', 'account_type': 'checking',
        'opening_balance': '5000.00', 'opening_date': '2026-01-01',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.bank_accounts.models import BankAccount
    ba = BankAccount.query.filter_by(code='BA-BPI').one()
    assert ba.account_id == cash_account.id and ba.branch_id == main_branch.id


def test_account_picker_excludes_claimed(client, accountant_user, db_session, main_branch, cash_account):
    _enable_bank_accounts(db_session)
    _login(client, accountant_user, main_branch)
    client.post('/bank-accounts/new', data={
        'code': 'BA-1', 'name': 'First', 'account_id': cash_account.id,
        'account_type': 'checking', 'opening_balance': '0',
    }, follow_redirects=True)
    resp = client.get('/bank-accounts/new')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert f'value="{cash_account.id}"' not in body


def test_sidebar_shows_bank_accounts_when_enabled(client, admin_user, db_session, main_branch):
    _enable_bank_accounts(db_session)
    _login(client, admin_user, main_branch)
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'bank_accounts.list_accounts' in body or 'bank-accounts' in body


def test_toggle_active(client, accountant_user, db_session, main_branch, cash_account):
    """Verify toggle_active endpoint flips is_active and logs the update."""
    _enable_bank_accounts(db_session)
    _login(client, accountant_user, main_branch)

    # Create a BankAccount directly
    from app.bank_accounts.models import BankAccount
    from app.audit.models import AuditLog
    ba = BankAccount(
        branch_id=main_branch.id, code='BA-TEST', name='Test Account',
        account_id=cash_account.id, account_type='checking',
        opening_balance=0, created_by='test'
    )
    db_session.add(ba)
    db_session.commit()
    original_id = ba.id
    assert ba.is_active is True

    # POST to toggle endpoint
    resp = client.post(f'/bank-accounts/{ba.id}/toggle-active', follow_redirects=True)
    assert resp.status_code == 200

    # Refresh from DB and assert flag flipped
    ba = db_session.get(BankAccount, original_id)
    assert ba.is_active is False

    # Assert audit log entry exists
    audit = AuditLog.query.filter_by(module='bank_accounts', action='update', record_id=ba.id).first()
    assert audit is not None
