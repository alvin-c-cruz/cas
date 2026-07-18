"""Book-item query tests (R-04 slice 3)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _je_line(db_session, branch, account, entry_number, debit=None, credit=None, status='posted'):
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    amt = debit or credit
    je = JournalEntry(entry_number=entry_number, entry_date=date(2026, 6, 10),
                      description='Test', entry_type='adjustment', branch_id=branch.id,
                      status=status, total_debit=amt, total_credit=amt, is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=account.id,
                                     debit_amount=(debit or 0), credit_amount=(credit or 0)))
    db_session.add(je); db_session.commit()
    return je.lines[0]


def _mk_bank_account(db_session, branch, account):
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=branch.id, code='BA-BI', name='BI',
                     account_id=account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    return ba


def test_uncleared_items_returns_lines_on_the_bank_account(db_session, main_branch, cash_account, revenue_account):
    from app.bank_reconciliation import service
    ba = _mk_bank_account(db_session, main_branch, cash_account)
    line = _je_line(db_session, main_branch, cash_account, 'JE-BI-0001', debit=Decimal('500'))
    _je_line(db_session, main_branch, revenue_account, 'JE-BI-0002', credit=Decimal('500'))  # different account
    items = service.uncleared_book_items(ba)
    assert line.id in {i.id for i in items}
    assert len(items) == 1   # the revenue_account line is excluded


def test_uncleared_items_excludes_already_cleared_lines(db_session, main_branch, cash_account):
    from app.bank_reconciliation import service
    from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem
    ba = _mk_bank_account(db_session, main_branch, cash_account)
    line = _je_line(db_session, main_branch, cash_account, 'JE-BI-0003', debit=Decimal('300'))
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('300'), beginning_balance=Decimal('0'),
                             status='completed')
    db_session.add(rec); db_session.commit()
    db_session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=line.id))
    db_session.commit()
    items = service.uncleared_book_items(ba)
    assert line.id not in {i.id for i in items}


def test_uncleared_items_excludes_unposted_entries(db_session, main_branch, cash_account):
    from app.bank_reconciliation import service
    ba = _mk_bank_account(db_session, main_branch, cash_account)
    _je_line(db_session, main_branch, cash_account, 'JE-BI-0004', debit=Decimal('100'), status='draft')
    items = service.uncleared_book_items(ba)
    assert items == []
