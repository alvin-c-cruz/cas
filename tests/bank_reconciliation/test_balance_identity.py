"""Balance identity + completion-blocked-until-zero tests (R-04 slice 3)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def test_reconciliation_summary_matches_identity(db_session, main_branch, cash_account):
    """book_balance - statement_balance == uncleared_debits - uncleared_credits."""
    from app.bank_reconciliation import service
    from app.bank_accounts.models import BankAccount
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    ba = BankAccount(branch_id=main_branch.id, code='BA-SUM', name='Sum',
                     account_id=cash_account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()

    # cleared deposit of 1000, uncleared deposit of 200 (in transit), uncleared check of 50
    for entry_number, debit, credit in [('JE-SUM-1', Decimal('1000'), None),
                                        ('JE-SUM-2', Decimal('200'), None),
                                        ('JE-SUM-3', None, Decimal('50'))]:
        je = JournalEntry(entry_number=entry_number, entry_date=date(2026, 6, 15),
                          description='t', entry_type='adjustment', branch_id=main_branch.id,
                          status='posted', total_debit=(debit or credit), total_credit=(debit or credit),
                          is_balanced=True)
        je.lines.append(JournalEntryLine(line_number=1, account_id=cash_account.id,
                                         debit_amount=(debit or 0), credit_amount=(credit or 0)))
        db_session.add(je)
    db_session.commit()

    from app.bank_reconciliation.models import BankReconciliation
    rec = BankReconciliation(bank_account_id=ba.id, statement_date=date(2026, 6, 30),
                             statement_ending_balance=Decimal('950.00'),   # 0 + 1000 - 50 = 950 cleared
                             beginning_balance=Decimal('0.00'))
    db_session.add(rec); db_session.commit()

    all_items = service.uncleared_book_items(ba)
    cleared_je_line = next(i for i in all_items if i.debit_amount == Decimal('1000'))
    check_je_line = next(i for i in all_items if i.credit_amount == Decimal('50'))
    ticked_ids = {cleared_je_line.id, check_je_line.id}   # tick the deposit AND the check -- leave the 200 in transit
    summary = service.reconciliation_summary(rec, ticked_ids)

    assert summary['difference'] == Decimal('0.00')   # balanced -> can complete
    assert summary['outstanding_deposits'] == Decimal('200.00')
