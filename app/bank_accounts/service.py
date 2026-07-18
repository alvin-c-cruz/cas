"""Service helpers for the Cash & Bank register (R-04 slice 1)."""
from app.accounts.models import Account
from app.settings import AppSettings

DEFAULT_CASH_BANK_PARENT_CODE = '10100'


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
