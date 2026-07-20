"""Service helpers for the Cash & Bank register (R-04 slice 1)."""
from app.accounts.models import Account
from app.bank_accounts.models import BankAccount
from app.settings import AppSettings

DEFAULT_CASH_BANK_PARENT_CODE = '10100'

# Mirrors app.bank_accounts.views._FIELDS -- kept as a separate constant (rather than
# imported from views) to avoid a service->views circular import (views already imports
# from service).
_AUDIT_FIELDS = ['code', 'name', 'account_id', 'bank_name', 'account_number', 'account_type',
                 'opening_balance', 'opening_date', 'is_active']


def get_cash_bank_parent_code():
    return (AppSettings.get_setting('cash_bank_parent_account_code') or DEFAULT_CASH_BANK_PARENT_CODE).strip()


def _leaf_accounts(parent):
    """Leaf (childless) descendants of `parent`, INCLUDING `parent` itself if it has no children.

    Filters to is_active=True only — inactive accounts and their entire subtrees are pruned.
    """
    if not parent.children:
        # Parent has no children; return it only if it is active
        return [parent] if parent.is_active else []
    out = []
    stack = list(parent.children)
    while stack:
        a = stack.pop()
        # Skip inactive accounts and their subtrees entirely
        if not a.is_active:
            continue
        if a.children:
            stack.extend(a.children)
        else:
            out.append(a)
    return out


def cash_bank_leaf_account_choices():
    code = get_cash_bank_parent_code()
    parent = Account.query.filter_by(code=code, is_active=True).first() if code else None
    if parent is None:
        leaves = [a for a in Account.query.filter_by(is_active=True).all() if not a.children]  # fail-soft: all leaves
    else:
        leaves = _leaf_accounts(parent)
    return [(a.id, f'{a.code} — {a.name}') for a in sorted(leaves, key=lambda a: a.code)]


def cash_bank_account_choices(branch_id):
    """ON -> the branch's active BankAccounts (value = the GL account_id, so posting is
    unchanged either way); OFF -> the fail-soft cash/bank leaf-account list."""
    from app.users.module_access import module_enabled
    if module_enabled('bank_accounts'):
        from app.bank_accounts.models import BankAccount
        rows = (BankAccount.query
                .filter_by(branch_id=branch_id, is_active=True)
                .order_by(BankAccount.code).all())
        return [(b.account_id, f'{b.code} - {b.name}') for b in rows]
    return cash_bank_leaf_account_choices()


def seed_bank_accounts_from_usage(created_by='system'):
    """One BankAccount per distinct cash/bank GL account_id already used on a posted
    JournalEntry, assigned to its max-usage branch. Shared-account (used by >1 branch)
    cases are flagged for manual split, never silently guessed. Read-only on JE/voucher
    tables -- creates BankAccount rows only."""
    from collections import defaultdict
    from app import db
    from app.audit.utils import log_create, model_to_dict
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    usage = defaultdict(int)          # (branch_id, account_id) -> line count
    rows = (db.session.query(JournalEntry.branch_id, JournalEntryLine.account_id)
            .join(JournalEntryLine, JournalEntryLine.entry_id == JournalEntry.id)
            .filter(JournalEntry.status == 'posted')
            .all())
    for branch_id, account_id in rows:
        usage[(branch_id, account_id)] += 1

    by_account = defaultdict(dict)    # account_id -> {branch_id: count}
    for (branch_id, account_id), n in usage.items():
        by_account[account_id][branch_id] = n

    cash_bank_ids = {aid for aid, _ in cash_bank_leaf_account_choices()}
    existing = {b.account_id for b in BankAccount.query.all()}

    flags = []
    for account_id, per_branch in by_account.items():
        if account_id in existing or account_id not in cash_bank_ids:
            continue
        win_branch = max(per_branch, key=per_branch.get)
        acct = db.session.get(Account, account_id)
        ba = BankAccount(branch_id=win_branch, account_id=account_id,
                         code=(acct.code or f'BA-{account_id}'), name=acct.name,
                         account_type='checking', opening_balance=0, created_by=created_by)
        db.session.add(ba)
        db.session.commit()
        log_create('bank_accounts', ba.id, ba.code, model_to_dict(ba, _AUDIT_FIELDS),
                  notes=f'Auto-seeded from posted journal-entry usage by {created_by}')
        others = [bid for bid in per_branch if bid != win_branch]
        if others:
            flags.append({'account_id': account_id, 'code': acct.code, 'name': acct.name,
                         'other_branch_ids': others})
    return flags
