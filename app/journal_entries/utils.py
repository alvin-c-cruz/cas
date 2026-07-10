"""Utility functions for journal entries."""
from datetime import datetime


# `JournalEntry.entry_number` carries a GLOBAL unique index, so a sequence scoped
# per branch mints the same number for every branch and violates that index on the
# second branch's first entry. Both sequences below are therefore COMPANY-WIDE.
# `branch_id` is still accepted so call sites read naturally, but it does not scope
# the sequence.


def next_sequence_number(prefix):
    """Next `{prefix}NNNN` across ALL branches, from the highest existing number."""
    from app.journal_entries.models import JournalEntry

    latest = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%')
    ).order_by(JournalEntry.entry_number.desc()).first()

    next_num = 1
    if latest:
        try:
            next_num = int(latest.entry_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            next_num = 1

    return f'{prefix}{next_num:04d}'


def generate_entry_number(branch_id=None):
    """Next internal JE number: JE-YYYY-####. Company-wide sequence."""
    return next_sequence_number(f'JE-{datetime.now().year}-')


def generate_jv_number(branch_id=None):
    """Next JV number: JV-YYYY-MM-NNNN. Company-wide sequence, resets each month."""
    from app.utils import ph_now
    now = ph_now()
    return next_sequence_number(f'JV-{now.year}-{now.month:02d}-')
