"""Helpers for the Opening Balances screen.

Opening balances are a single posted "opening_balance" JournalEntry per branch.
No new model: these helpers locate that entry, compute its lock state, and
produce the leaf-only account picker data the screen needs.
"""
from app.journal_entries.models import JournalEntry
from app.accounts.models import Account
from app.settings import AppSettings
from app.periods.utils import is_period_closed

OPENING_ENTRY_TYPE = 'opening_balance'
ACTIVE_STATUSES = ('draft', 'posted')


def LOCK_KEY(branch_id):
    """AppSettings key holding the per-branch finalize lock flag ('1'/'0')."""
    return f'opening_balance_finalized:{branch_id}'


def get_opening_entry(branch_id):
    """The single active (draft|posted) opening-balance JE for a branch, or None."""
    return JournalEntry.query.filter(
        JournalEntry.entry_type == OPENING_ENTRY_TYPE,
        JournalEntry.branch_id == branch_id,
        JournalEntry.status.in_(ACTIVE_STATUSES),
    ).first()


def is_opening_locked(branch_id):
    """Locked when finalized by an admin OR the opening entry sits in a closed period."""
    if AppSettings.get_setting(LOCK_KEY(branch_id), '0') == '1':
        return True
    entry = get_opening_entry(branch_id)
    if entry and is_period_closed(entry.entry_date):
        return True
    return False


def opening_account_choices():
    """All active accounts as dicts with is_group + depth for the Choices.js picker.

    Group accounts (top-level or having children) are shown but non-selectable.
    Mirrors app/accounts_payable/views.py::_get_all_accounts_for_select.
    """
    all_accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}
    id_map = {a.id: a for a in all_accts}

    def _depth(acct):
        d, p, visited = 0, acct.parent_id, set()
        while p and p in id_map and p not in visited:
            visited.add(p)
            d += 1
            p = id_map[p].parent_id
        return d

    result = []
    for a in all_accts:
        d = a.to_dict()
        d['is_group'] = a.id in parent_ids
        d['depth'] = _depth(a)
        result.append(d)
    return result


def opening_leaf_account_ids():
    """Ids of postable (non-group) active accounts — server-side allowlist."""
    return {a['id'] for a in opening_account_choices() if not a['is_group']}
