"""Service helpers for the Cash & Bank register (R-04 slice 1)."""
from app.accounts.models import Account
from app.settings import AppSettings

DEFAULT_CASH_BANK_PARENT_CODE = '10100'


def get_cash_bank_parent_code():
    return (AppSettings.get_setting('cash_bank_parent_account_code') or DEFAULT_CASH_BANK_PARENT_CODE).strip()


def _leaf_accounts(parent):
    """Leaf (childless) descendants of `parent`, INCLUDING `parent` itself if it has no children."""
    if not parent.children:
        return [parent]
    out = []
    stack = list(parent.children)
    while stack:
        a = stack.pop()
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
