"""Utility functions for journal entries."""
from datetime import datetime


# `JournalEntry.entry_number` carries a GLOBAL unique index, so a sequence scoped
# per branch mints the same number for every branch and violates that index on the
# second branch's first entry. Both sequences below are therefore COMPANY-WIDE.
# `branch_id` is still accepted so call sites read naturally, but it does not scope
# the sequence.


def next_sequence_number(prefix):
    """Next `{prefix}NNNN` across ALL branches: one more than the NUMERIC max suffix.

    Never the lexicographically-last row: as strings 'JV-2026-08-9999' sorts after
    'JV-2026-08-10000', and taking it would hand out 10000 a second time
    (CAS-DEVELOPMENT.md, "Document numbering").
    """
    from app.journal_entries.models import JournalEntry

    numbers = JournalEntry.query.with_entities(JournalEntry.entry_number).filter(
        JournalEntry.entry_number.like(f'{prefix}%')
    ).all()

    highest = 0
    for (number,) in numbers:
        try:
            highest = max(highest, int(number[len(prefix):]))
        except (ValueError, TypeError):
            continue

    return f'{prefix}{highest + 1:04d}'


def generate_entry_number(branch_id=None):
    """Next internal JE number: JE-YYYY-####. Company-wide sequence."""
    return next_sequence_number(f'JE-{datetime.now().year}-')


def jv_prefix(entry_date=None):
    """`JV-YYYY-MM-` for the month the voucher is DATED in (today when no date)."""
    if entry_date is None:
        from app.utils import ph_now
        entry_date = ph_now().date()
    return f'JV-{entry_date.year}-{entry_date.month:02d}-'


def generate_jv_number(branch_id=None, entry_date=None):
    """Next JV number: JV-YYYY-MM-NNNN. Company-wide sequence, resets each month.

    The month is the ENTRY DATE's, not today's (owner, 2026-10-01): a JV dated
    31 Aug entered on 1 Oct is JV-2026-08-xxxx. With no date it falls back to today.
    """
    return next_sequence_number(jv_prefix(entry_date))
