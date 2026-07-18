"""CRV/CDV cash-account picker swap tests (R-04 slice 1)."""
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


def _bank_account(db_session, branch, account, code='BA-1'):
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=branch.id, code=code, name='BPI Main', account_id=account.id,
                     account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    return ba


def test_choices_on_are_branch_bank_accounts(db_session, main_branch, branch_manila, cash_account):
    from app.bank_accounts import service
    _enable_bank_accounts(db_session)
    ba = _bank_account(db_session, main_branch, cash_account)
    choices = service.cash_bank_account_choices(main_branch.id)
    assert (ba.account_id, f'{ba.code} - {ba.name}') in choices
    # a different branch with no bank accounts of its own sees none
    assert service.cash_bank_account_choices(branch_manila.id) == []


def test_choices_off_are_cash_bank_leaves(db_session, main_branch, cash_account):
    from app.bank_accounts import service
    # Guard against cross-test cache pollution: get_module_override() is memoized on the
    # session-scoped cache, which survives the per-test db_session table drop/recreate, so a
    # sibling test enabling the module earlier in file order can otherwise leak a stale '1' here.
    clear_module_config_cache()
    choices = service.cash_bank_account_choices(main_branch.id)   # module never enabled in this test
    ids = {aid for aid, _ in choices}
    assert cash_account.id in ids


def test_crv_create_form_uses_bank_account_choices_when_on(client, accountant_user, db_session,
                                                            main_branch, cash_account):
    _enable_bank_accounts(db_session)
    _bank_account(db_session, main_branch, cash_account, code='BA-PICK')
    _login(client, accountant_user, main_branch)
    resp = client.get('/cash-receipts/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'BA-PICK - BPI Main' in body
