"""The one seam every financial report reads posted journal lines through.

Two bases (app/reports/basis.py): GAAP is the posted lines exactly as booked; OWNERS is the
same lines with VAT legs re-pointed by app/reports/owners_ledger.py. Report generators never
query JournalEntryLine for balances themselves; they call period_balances() or
ledger_lines() here, so a basis is a parameter, not seven copies of VAT logic.

Filters mirror what the generators did before this seam: posted entries only; branch when
given; date bounds when given (None = unbounded); closing/closing-reversal entries excluded
only when the caller says so (P&L-period reports exclude them, balance reports include them).

The owners' path is computed once per (start, end, branch, exclude_closing) per request and
cached on flask.g, which the reports blueprint resets in before_request. Outside a request
nothing is cached.
"""
from collections import defaultdict, namedtuple
from decimal import Decimal

from flask import g, has_request_context
from sqlalchemy import func

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.basis import GAAP, OWNERS

CLOSING_TYPES = ('closing', 'closing_reversal')
ZERO = Decimal('0.00')

LedgerLine = namedtuple('LedgerLine', [
    'line_id', 'entry_id', 'entry_number', 'display_number', 'entry_date', 'entry_type',
    'reference', 'description', 'line_number', 'reversed_entry_id',
    'account_id', 'debit', 'credit', 'moved_from_account_id',
])


def _d(x):
    return Decimal(str(x or 0)).quantize(Decimal('0.01'))


def _filters(start, end, branch_id, exclude_closing):
    f = [JournalEntry.status == 'posted']
    if branch_id:
        f.append(JournalEntry.branch_id == branch_id)
    if start is not None:
        f.append(JournalEntry.entry_date >= start)
    if end is not None:
        f.append(JournalEntry.entry_date <= end)
    if exclude_closing:
        f.append(JournalEntry.entry_type.notin_(CLOSING_TYPES))
    return f


def fetch_lines(start, end, branch_id, exclude_closing=False):
    """Raw posted lines as LedgerLine, ordered (date, entry_number, line_number)."""
    rows = db.session.query(JournalEntryLine, JournalEntry).join(JournalEntry).filter(
        *_filters(start, end, branch_id, exclude_closing)
    ).order_by(JournalEntry.entry_date, JournalEntry.entry_number, JournalEntryLine.line_number).all()
    return [LedgerLine(
        line_id=l.id, entry_id=e.id, entry_number=e.entry_number, display_number=e.display_number,
        entry_date=e.entry_date, entry_type=e.entry_type, reference=e.reference,
        description=l.description or e.description, line_number=l.line_number,
        reversed_entry_id=e.reversed_entry_id, account_id=l.account_id,
        debit=_d(l.debit_amount), credit=_d(l.credit_amount), moved_from_account_id=None,
    ) for l, e in rows]


def _gaap_balances(start, end, branch_id, exclude_closing):
    rows = db.session.query(
        JournalEntryLine.account_id,
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(*_filters(start, end, branch_id, exclude_closing)
                                ).group_by(JournalEntryLine.account_id).all()
    return {aid: (_d(d), _d(c)) for aid, d, c in rows}


def _owners(start, end, branch_id, exclude_closing):
    """(remapped lines, RemapSummary), cached per request. Task 6 fills this in."""
    raise NotImplementedError('owners basis lands in Task 6')


def period_balances(start, end, branch_id, reporting_basis=GAAP, exclude_closing=False):
    """{account_id: (debit_sum, credit_sum)} over posted lines in scope."""
    if reporting_basis != OWNERS:
        return _gaap_balances(start, end, branch_id, exclude_closing)
    lines, _ = _owners(start, end, branch_id, exclude_closing)
    acc = defaultdict(lambda: [ZERO, ZERO])
    for ln in lines:
        acc[ln.account_id][0] += ln.debit
        acc[ln.account_id][1] += ln.credit
    return {aid: (d, c) for aid, (d, c) in acc.items()}


def ledger_lines(start, end, branch_id, reporting_basis=GAAP, account_id=None, exclude_closing=False):
    """Posted lines in scope, ordered; optionally only one account's."""
    if reporting_basis != OWNERS:
        lines = fetch_lines(start, end, branch_id, exclude_closing)
    else:
        lines, _ = _owners(start, end, branch_id, exclude_closing)
    if account_id is not None:
        lines = [l for l in lines if l.account_id == account_id]
    return lines


def owners_summary(start, end, branch_id, exclude_closing=False):
    """The RemapSummary for the scope (what moved where, what stayed flagged)."""
    return _owners(start, end, branch_id, exclude_closing)[1]
