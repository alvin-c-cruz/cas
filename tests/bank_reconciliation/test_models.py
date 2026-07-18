"""Unit tests for BankReconciliation + ReconciliationItem models (R-04 slice 3)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.bank_reconciliation.models import BankReconciliation, ReconciliationItem

pytestmark = [pytest.mark.integration]


def _mk_bank_account(db_session, branch, account, code='BA-1'):
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=branch.id, code=code, name='BPI Main',
                     account_id=account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    return ba


def test_default_status_draft(db_session, main_branch, cash_account):
    ba = _mk_bank_account(db_session, main_branch, cash_account)
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('10000.00'),
                             beginning_balance=Decimal('9000.00'))
    db_session.add(rec); db_session.commit()
    assert rec.status == 'draft'
    assert rec.row_version == 1


def test_je_line_id_unique_across_reconciliation_items(db_session, main_branch, cash_account):
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    ba = _mk_bank_account(db_session, main_branch, cash_account)
    je = JournalEntry(entry_number='JE-REC-0001', entry_date=date(2026, 6, 15),
                      description='Test', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', total_debit=Decimal('100'), total_credit=Decimal('100'),
                      is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=cash_account.id,
                                     debit_amount=Decimal('100'), credit_amount=0))
    db_session.add(je); db_session.commit()
    line_id = je.lines[0].id

    rec1 = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                              statement_ending_balance=Decimal('100'), beginning_balance=Decimal('0'))
    rec2 = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 7, 31),
                              statement_ending_balance=Decimal('100'), beginning_balance=Decimal('0'))
    db_session.add_all([rec1, rec2]); db_session.commit()

    db_session.add(ReconciliationItem(reconciliation_id=rec1.id, je_line_id=line_id))
    db_session.commit()
    db_session.add(ReconciliationItem(reconciliation_id=rec2.id, je_line_id=line_id))
    with pytest.raises(Exception):        # unique index rejects clearing the same line twice
        db_session.commit()
    db_session.rollback()
