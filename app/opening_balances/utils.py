"""Helpers for the Opening Balances screen.

Opening balances are a single posted "opening_balance" JournalEntry per branch.
No new model: these helpers locate that entry, compute its lock state, and
produce the leaf-only account picker data the screen needs.
"""
from app.journal_entries.models import JournalEntry
from app.accounts.models import Account
from app.periods.utils import is_period_closed

OPENING_ENTRY_TYPE = 'opening_balance'
ACTIVE_STATUSES = ('draft', 'posted')


def get_opening_entry(branch_id):
    """The single active (draft|posted) opening-balance JE for a branch, or None."""
    return JournalEntry.query.filter(
        JournalEntry.entry_type == OPENING_ENTRY_TYPE,
        JournalEntry.branch_id == branch_id,
        JournalEntry.status.in_(ACTIVE_STATUSES),
    ).first()


def is_opening_locked(branch_id):
    """Locked (governed) when the opening entry sits in a closed period."""
    entry = get_opening_entry(branch_id)
    return bool(entry and is_period_closed(entry.entry_date))


def opening_account_choices():
    """All active accounts as dicts with is_group + depth for the Choices.js picker.

    Group accounts (those with sub-accounts) are shown but non-selectable.
    """
    # ACCT-PICK (owner 14 Nov 2026): the one postable-account rule, app/accounts/postable.py.
    from app.accounts.postable import picker_rows
    return picker_rows()


def opening_leaf_account_ids():
    """Ids of postable (non-group) active accounts — server-side allowlist."""
    return {a['id'] for a in opening_account_choices() if not a['is_group']}
