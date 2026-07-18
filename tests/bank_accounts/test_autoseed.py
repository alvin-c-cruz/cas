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
