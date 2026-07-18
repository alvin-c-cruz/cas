"""Completion freezes snapshot totals; a later backdated JE does NOT change them
(R-04 slice 3). Also proves double-complete is rejected by claim_version, using
an EXPLICIT submitted-token parameter (not rec.row_version read fresh from the
same in-memory object) -- the "read-then-compare defeats the guard" trap."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _mk_rec_with_one_cleared_line(db_session, main_branch, cash_account):
    from app.bank_accounts.models import BankAccount
    from app.bank_reconciliation.models import BankReconciliation
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    ba = BankAccount(branch_id=main_branch.id, code='BA-SNAP', name='Snap',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    je = JournalEntry(entry_number='JE-SNAP-0001', entry_date=date(2026, 6, 10),
                      description='t', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', total_debit=Decimal('500'), total_credit=Decimal('500'),
                      is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=cash_account.id,
                                     debit_amount=Decimal('500'), credit_amount=0))
    db_session.add(je); db_session.commit()
    line_id = je.lines[0].id
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('500.00'), beginning_balance=Decimal('0.00'))
    db_session.add(rec); db_session.commit()
    return rec, ba, line_id


def test_complete_freezes_snapshot_totals(db_session, main_branch, cash_account, admin_user):
    from app.bank_reconciliation import service
    rec, ba, line_id = _mk_rec_with_one_cleared_line(db_session, main_branch, cash_account)
    token = rec.row_version
    ok = service.complete_reconciliation(rec, {line_id}, token, admin_user)
    db_session.commit()
    assert ok is True
    assert rec.status == 'completed'
    assert rec.adjusted_balance == Decimal('500.00')
    assert rec.reconciled_by_id == admin_user.id


def test_backdated_je_does_not_change_completed_snapshot(db_session, main_branch, cash_account, admin_user):
    from app.bank_reconciliation import service
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    rec, ba, line_id = _mk_rec_with_one_cleared_line(db_session, main_branch, cash_account)
    service.complete_reconciliation(rec, {line_id}, rec.row_version, admin_user)
    db_session.commit()
    frozen_balance = rec.adjusted_balance

    # backdate a NEW JE into the already-reconciled period
    late_je = JournalEntry(entry_number='JE-SNAP-LATE', entry_date=date(2026, 6, 20),
                           description='late entry', entry_type='adjustment', branch_id=main_branch.id,
                           status='posted', total_debit=Decimal('999'), total_credit=Decimal('999'),
                           is_balanced=True)
    late_je.lines.append(JournalEntryLine(line_number=1, account_id=cash_account.id,
                                          debit_amount=Decimal('999'), credit_amount=0))
    db_session.add(late_je); db_session.commit()

    db_session.refresh(rec)
    assert rec.adjusted_balance == frozen_balance   # unchanged -- the historical report is immutable

    next_items = service.uncleared_book_items(ba)
    assert late_je.lines[0].id in {i.id for i in next_items}   # shows up as uncleared in the NEXT rec


def test_double_complete_second_writer_loses(db_session, main_branch, cash_account, admin_user):
    from app.bank_reconciliation import service
    rec, ba, line_id = _mk_rec_with_one_cleared_line(db_session, main_branch, cash_account)
    stale_token = rec.row_version   # captured BEFORE either call -- simulates a stale browser tab
    first = service.complete_reconciliation(rec, {line_id}, stale_token, admin_user)
    db_session.commit()
    second = service.complete_reconciliation(rec, {line_id}, stale_token, admin_user)   # same stale token, second racer
    assert first is True
    assert second is False


def test_complete_blocked_while_difference_nonzero(db_session, main_branch, cash_account, admin_user):
    from app.bank_reconciliation import service
    from app.bank_accounts.models import BankAccount
    from app.bank_reconciliation.models import BankReconciliation
    ba = BankAccount(branch_id=main_branch.id, code='BA-UNBAL', name='Unbal',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('9999.00'),   # nothing ties to this
                             beginning_balance=Decimal('0.00'))
    db_session.add(rec); db_session.commit()
    ok = service.complete_reconciliation(rec, set(), rec.row_version, admin_user)
    db_session.commit()
    assert ok is False
    assert rec.status == 'draft'   # refused, not silently completed
