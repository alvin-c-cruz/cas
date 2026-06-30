import pytest
from datetime import date
from app import db
from app.opening_balances.utils import (
    LOCK_KEY, get_opening_entry, is_opening_locked,
    opening_account_choices, opening_leaf_account_ids,
)
from app.journal_entries.models import JournalEntry
from app.accounts.models import Account
from app.settings import AppSettings
from app.periods.models import AccountingPeriod

pytestmark = [pytest.mark.unit]


def _opening_je(branch_id, status='draft', entry_date=date(2026, 1, 1)):
    je = JournalEntry(
        entry_number=f'JV-2026-01-000{branch_id}', entry_date=entry_date,
        description='Opening Balances', reference='OPENING BALANCES',
        entry_type='opening_balance', status=status, branch_id=branch_id,
        total_debit=0, total_credit=0, is_balanced=True,
    )
    db.session.add(je)
    db.session.commit()
    return je


def test_lock_key_embeds_branch_id():
    assert LOCK_KEY(7) == 'opening_balance_finalized:7'


def test_get_opening_entry_returns_only_active_for_branch(db_session, main_branch, branch_manila):
    _opening_je(main_branch.id, status='posted')
    assert get_opening_entry(main_branch.id) is not None
    assert get_opening_entry(branch_manila.id) is None


def test_get_opening_entry_ignores_cancelled(db_session, main_branch):
    _opening_je(main_branch.id, status='cancelled')
    assert get_opening_entry(main_branch.id) is None


def test_is_opening_locked_false_by_default(db_session, main_branch):
    _opening_je(main_branch.id, status='posted')
    assert is_opening_locked(main_branch.id) is False


def test_is_opening_locked_true_when_finalized(db_session, main_branch):
    _opening_je(main_branch.id, status='posted')
    AppSettings.set_setting(LOCK_KEY(main_branch.id), '1', updated_by='admin')
    assert is_opening_locked(main_branch.id) is True


def test_is_opening_locked_true_when_period_closed(db_session, main_branch):
    _opening_je(main_branch.id, status='posted', entry_date=date(2026, 1, 1))
    db.session.add(AccountingPeriod(year=2026, month=1, status='closed'))
    db.session.commit()
    assert is_opening_locked(main_branch.id) is True


def test_leaf_account_helpers_exclude_group_accounts(db_session):
    parent = Account(code='1000', name='Assets', account_type='Asset',
                     normal_balance='Debit', is_active=True)
    db.session.add(parent)
    db.session.commit()
    child = Account(code='1001', name='Cash', account_type='Asset',
                    normal_balance='Debit', is_active=True, parent_id=parent.id)
    db.session.add(child)
    db.session.commit()
    standalone = Account(code='9999', name='Standalone Top-Level', account_type='Asset',
                         normal_balance='Debit', is_active=True)
    db.session.add(standalone)
    db.session.commit()

    leaf_ids = opening_leaf_account_ids()
    assert child.id in leaf_ids
    assert parent.id not in leaf_ids
    assert standalone.id not in leaf_ids

    by_id = {a['id']: a for a in opening_account_choices()}
    assert by_id[parent.id]['is_group'] is True
    assert by_id[child.id]['is_group'] is False
    assert by_id[standalone.id]['is_group'] is True
