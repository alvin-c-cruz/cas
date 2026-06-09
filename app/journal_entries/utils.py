"""Utility functions for journal entries."""
from datetime import datetime


def generate_entry_number(branch_id):
    """Generate next JE number for a branch: JE-YYYY-####. Per-branch independent sequence."""
    from app.journal_entries.models import JournalEntry
    current_year = datetime.now().year
    prefix = f'JE-{current_year}-'

    latest_entry = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%'),
        JournalEntry.branch_id == branch_id
    ).order_by(JournalEntry.entry_number.desc()).first()

    if latest_entry:
        try:
            last_num = int(latest_entry.entry_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'
