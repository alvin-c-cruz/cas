"""Book-item query + the reconciliation balance identity (R-04 slice 3)."""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.utils.concurrency import claim_version
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
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


def post_adjustment(rec, account_id, amount, direction, description, actor):
    """Bank-only item (service charge, interest, error) -- posts an ordinary
    balanced 2-line JE (bank leg + the chosen contra account) and auto-clears
    the bank-side line in THIS reconciliation, since it's known to be on the
    statement. `direction` is 'debit' or 'credit' as seen from the BANK leg
    (e.g. a service charge is a credit to the bank -- money left the account).
    entry_type='adjustment' -- the app's own generic ad-hoc-JE type (already the
    JournalEntry model's default, already registered in VOUCHER_TYPES/
    VOUCHER_ENTRY_TYPES), the same convention petty_cash's establish/adjust/
    close JEs already use for a pure balance-adjusting event with no document
    shape of its own."""
    assert direction in ('debit', 'credit')
    bank_debit = amount if direction == 'debit' else Decimal('0.00')
    bank_credit = amount if direction == 'credit' else Decimal('0.00')
    contra_debit = amount if direction == 'credit' else Decimal('0.00')
    contra_credit = amount if direction == 'debit' else Decimal('0.00')

    je = JournalEntry(entry_number=generate_entry_number(rec.bank_account.branch_id),
                      entry_date=rec.statement_date, description=description,
                      entry_type='adjustment', branch_id=rec.bank_account.branch_id,
                      status='posted', posted_by_id=actor.id, posted_at=ph_now(),
                      total_debit=amount, total_credit=amount, is_balanced=True)
    je.lines.append(JournalEntryLine(line_number=1, account_id=rec.bank_account.account_id,
                                     description=description,
                                     debit_amount=bank_debit, credit_amount=bank_credit))
    je.lines.append(JournalEntryLine(line_number=2, account_id=account_id, description=description,
                                     debit_amount=contra_debit, credit_amount=contra_credit))
    db.session.add(je); db.session.flush()
    bank_line = je.lines[0]
    db.session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=bank_line.id))
    return bank_line


def complete_reconciliation(rec, ticked_line_ids, submitted_version, actor):
    """Freeze the ReconciliationItem set + snapshot totals. Returns False (does
    NOT raise) for either a lost optimistic-lock race or a nonzero difference --
    both are normal, expected outcomes an accountant should see as a flash, not
    a 500. `submitted_version` must be the token the CALLER actually saw (the
    view passes `submitted_version()`, read from the raw POST body -- never
    `rec.row_version` re-read fresh from the same in-memory object, which would
    never be stale within one request and would defeat the guard)."""
    summary = reconciliation_summary(rec, ticked_line_ids)
    if summary['difference'] != Decimal('0.00'):
        return False

    if not claim_version(type(rec), rec.id, submitted_version):
        return False

    for line_id in ticked_line_ids:
        already = ReconciliationItem.query.filter_by(reconciliation_id=rec.id, je_line_id=line_id).first()
        if not already:
            db.session.add(ReconciliationItem(reconciliation_id=rec.id, je_line_id=line_id))

    rec.status = 'completed'
    rec.book_balance = summary['book_balance']
    rec.cleared_debits = summary['cleared_debits']
    rec.cleared_credits = summary['cleared_credits']
    rec.outstanding_deposits = summary['outstanding_deposits']
    rec.outstanding_checks = summary['outstanding_checks']
    rec.adjusted_balance = summary['adjusted_balance']
    rec.reconciled_by_id = actor.id
    rec.reconciled_at = ph_now()
    return True
