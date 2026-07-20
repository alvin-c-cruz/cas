"""OFF->ON auto-seed tests (R-04 slice 1)."""
from decimal import Decimal
from datetime import date
import pytest
from app import db
from app.bank_accounts.models import BankAccount

pytestmark = [pytest.mark.integration]


def _posted_je_on(db_session, account, branch, entry_number, debit=True, status='posted'):
    """A minimal JournalEntry (posted by default) with one line on `account` -- the seeder
    reads JournalEntry/JournalEntryLine directly, so the test builds those tables directly
    rather than going through a voucher's own posting cascade (decoupling this test
    from CRV/CDV's own posting mechanics, which aren't what's under test here)."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    amt = Decimal('1000.00')
    je = JournalEntry(entry_number=entry_number, entry_date=date(2026, 7, 1),
                      description='Test cash movement', entry_type='adjustment',
                      branch_id=branch.id, status=status,
                      total_debit=amt, total_credit=amt, is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=account.id,
                                     description='Cash leg',
                                     debit_amount=(amt if debit else 0),
                                     credit_amount=(0 if debit else amt)))
    db_session.add(je); db_session.commit()
    return je


def test_seed_single_branch_usage(db_session, main_branch, cash_account):
    from app.bank_accounts import service
    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0001')
    flags = service.seed_bank_accounts_from_usage()
    ba = BankAccount.query.filter_by(account_id=cash_account.id).one()
    assert ba.branch_id == main_branch.id
    assert flags == []


def test_seed_shared_account_flags_others(db_session, main_branch, branch_manila, cash_account):
    from app.bank_accounts import service
    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0002')
    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0003')
    _posted_je_on(db_session, cash_account, branch_manila, 'JE-SEED-0004')
    flags = service.seed_bank_accounts_from_usage()
    ba = BankAccount.query.filter_by(account_id=cash_account.id).one()      # unique -> exactly one row
    assert ba.branch_id == main_branch.id                                  # max-usage branch wins (2 vs 1)
    assert flags and flags[0]['account_id'] == cash_account.id
    assert branch_manila.id in flags[0]['other_branch_ids']


def test_seed_is_idempotent(db_session, main_branch, cash_account):
    from app.bank_accounts import service
    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0005')
    service.seed_bank_accounts_from_usage()
    service.seed_bank_accounts_from_usage()                                # 2nd run creates nothing
    assert BankAccount.query.filter_by(account_id=cash_account.id).count() == 1


def test_seed_never_creates_or_modifies_journal_entries(db_session, main_branch, cash_account):
    from app.bank_accounts import service
    from app.journal_entries.models import JournalEntry
    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0006')
    before = {(je.id, je.total_debit) for je in JournalEntry.query.all()}
    service.seed_bank_accounts_from_usage()
    after = {(je.id, je.total_debit) for je in JournalEntry.query.all()}
    assert before == after


def test_seed_filters_to_posted_journal_entries_only(db_session, main_branch, cash_account):
    """A DRAFT-only account must not be seeded -- the seeder's own docstring says
    "already used on a posted JournalEntry"; a JE line still in DRAFT is not that yet."""
    from app.accounts.models import Account
    from app.bank_accounts import service

    draft_only_account = Account(code='1002', name='Petty Cash Fund', account_type='Asset',
                                 classification='Current Asset', normal_balance='Debit',
                                 description='Draft-only test account')
    db_session.add(draft_only_account); db_session.commit()

    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0007')                        # posted
    _posted_je_on(db_session, draft_only_account, main_branch, 'JE-SEED-0008', status='draft')  # draft

    service.seed_bank_accounts_from_usage()

    assert BankAccount.query.filter_by(account_id=cash_account.id).count() == 1
    assert BankAccount.query.filter_by(account_id=draft_only_account.id).count() == 0


def test_seed_logs_audit_entry_for_seeded_bank_account(db_session, main_branch, cash_account):
    """Every other BankAccount-creation path (new_account/quick_add) calls log_create;
    the seeder must too."""
    from app.audit.models import AuditLog
    from app.bank_accounts import service

    _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0009')
    service.seed_bank_accounts_from_usage(created_by='system')

    ba = BankAccount.query.filter_by(account_id=cash_account.id).one()
    audit = AuditLog.query.filter_by(module='bank_accounts', action='create', record_id=ba.id).first()
    assert audit is not None
    assert audit.record_identifier == ba.code


def test_toggle_on_survives_seeder_failure(client, db_session, admin_user, main_branch, login_user, monkeypatch):
    """Guard on modules_toggle(): the module is already durably ON (AppSettings write
    commits first) before the seeder runs, and the seeder now commits per-row -- so a
    failure partway through must not 500 and must tell the admin the seed may be
    incomplete and that a retry (off then on) is safe (the seeder recomputes what's
    already registered on every call)."""
    from app.settings import AppSettings
    from app.bank_accounts import service
    from app.utils.cache_helpers import clear_module_config_cache

    def _boom(created_by='system'):
        raise RuntimeError('simulated seeder failure')

    monkeypatch.setattr(service, 'seed_bank_accounts_from_usage', _boom)

    try:
        login_user(client, 'admin', 'admin123')
        resp = client.post('/settings/modules/toggle',
                           data={'key': 'bank_accounts', 'enable': '1'},
                           follow_redirects=True)

        assert resp.status_code == 200                                             # no unhandled 500
        assert AppSettings.get_setting('module_enabled:bank_accounts') == '1'      # module stays ON
        assert b'did not complete' in resp.data                                    # incomplete-seed flash
        assert b'safe to retry' in resp.data or b'retry' in resp.data.lower()
    finally:
        # module_enabled() is memoized on the session-scoped app cache, which outlives this
        # test's db_session table drop/recreate -- clear it so a later test in the same run
        # doesn't see a stale '1' for an AppSettings row that no longer exists (see the same
        # guard in test_picker.py).
        clear_module_config_cache()


def test_toggle_on_warning_names_the_specific_accounts_and_branches(
        client, db_session, admin_user, main_branch, branch_manila, cash_account, login_user):
    """BUG-BANKACCT-SHARED-ACCOUNT-NO-REASSIGN: the old warning just said "N cash
    account(s) are used by more than one branch" with no indication of WHICH account
    or WHICH branches, and never mentioned that creating the new Bank Account has to
    happen while viewing the other branch (BankAccount.branch_id is silently taken
    from the current session branch at creation -- there is no branch_id form field).
    The message must name the specific account and the specific other branch(es), and
    spell out the branch-switch step."""
    from app.utils.cache_helpers import clear_module_config_cache
    try:
        _posted_je_on(db_session, cash_account, main_branch, 'JE-SEED-0010')
        _posted_je_on(db_session, cash_account, branch_manila, 'JE-SEED-0011')

        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.post('/settings/modules/toggle',
                           data={'key': 'bank_accounts', 'enable': '1'},
                           follow_redirects=True)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert cash_account.code in body                    # names the specific account
        assert cash_account.name in body
        assert branch_manila.name in body                    # names the specific other branch
        assert 'switch' in body.lower()                       # spells out the branch-switch step
    finally:
        clear_module_config_cache()
