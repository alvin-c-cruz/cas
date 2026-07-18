"""Book-item query + the reconciliation balance identity (R-04 slice 3)."""
from decimal import Decimal
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.bank_reconciliation.models import ReconciliationItem


def uncleared_book_items(bank_account, exclude_reconciliation_id=None):
    """Every posted JournalEntryLine on this bank account's GL account + branch,
    not yet cleared in ANY completed or draft reconciliation OTHER than
    `exclude_reconciliation_id` (pass the current draft's own id when re-opening
    its work page, so its own already-ticked items still show as "ticked", not
    filtered out of the page entirely)."""
    cleared_line_ids_q = db.session.query(ReconciliationItem.je_line_id)
    if exclude_reconciliation_id is not None:
        cleared_line_ids_q = cleared_line_ids_q.filter(
            ReconciliationItem.reconciliation_id != exclude_reconciliation_id)
    cleared_line_ids = {row[0] for row in cleared_line_ids_q.all()}

    lines = (JournalEntryLine.query
             .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
             .filter(JournalEntryLine.account_id == bank_account.account_id,
                     JournalEntry.branch_id == bank_account.branch_id,
                     JournalEntry.status == 'posted')
             .order_by(JournalEntry.entry_date, JournalEntryLine.id).all())
    return [l for l in lines if l.id not in cleared_line_ids]


def reconciliation_summary(rec, ticked_line_ids):
    """Live summary for a DRAFT rec. For a COMPLETED rec, read the snapshot
    columns directly instead of calling this (the detail view makes that
    distinction, not this function)."""
    all_uncleared = uncleared_book_items(rec.bank_account, exclude_reconciliation_id=rec.id)
    cleared = [l for l in all_uncleared if l.id in ticked_line_ids]
    outstanding = [l for l in all_uncleared if l.id not in ticked_line_ids]

    cleared_debits = sum((l.debit_amount for l in cleared), Decimal('0.00'))
    cleared_credits = sum((l.credit_amount for l in cleared), Decimal('0.00'))
    outstanding_deposits = sum((l.debit_amount for l in outstanding), Decimal('0.00'))
    outstanding_checks = sum((l.credit_amount for l in outstanding), Decimal('0.00'))

    book_balance = rec.beginning_balance + cleared_debits - cleared_credits
    adjusted_balance = book_balance
    difference = (rec.statement_ending_balance - adjusted_balance).quantize(Decimal('0.01'))

    return {
        'book_balance': book_balance, 'cleared_debits': cleared_debits,
        'cleared_credits': cleared_credits, 'outstanding_deposits': outstanding_deposits,
        'outstanding_checks': outstanding_checks, 'adjusted_balance': adjusted_balance,
        'difference': difference,
    }
