"""Which accounts can be posted to -- ONE rule for every account picker (ACCT-PICK, owner 14 Nov 2026: "ACCT-PICK shared
helper"; ACCT-RULE, 17 Nov 2026: "B (my pick)"; triage BUG-ACCOUNT-PICKER-CHILDLESS-TOPLEVEL-POSTABLE).

The rule: an account is a HEADER (shown, not selectable, never posted to) when another ACTIVE account has it as its
parent -- it has sub-accounts. Every other active account is postable, a top-level one with no sub-accounts included.

Twelve pickers used two rules: nine tested "has sub-accounts" (this one), three -- opening balances, control accounts,
fixed assets -- also treated every top-level account as a header. The owner chose the looser rule for all (ACCT-RULE
B), so a top-level account with no sub-accounts yet (RIC: 119000 Other Current Assets, 229000 Non Current Liabilities,
611000 Cost of Sales; Philgen: 115000 Supplies Inventory, 116000 Prepayments) is postable everywhere; to close one off,
give it a sub-account or mark it inactive. The stricter rule was built first and broke 221 tests whose charts are flat.
Every picker reads this module; a change to the rule is made here and nowhere else.
"""
from app.accounts.models import Account


def active_accounts():
    """Active accounts, code order. A direct query on purpose: the cached account helpers are not invalidated on
    account create/update/approve, so a picker built from them can be stale."""
    return Account.query.filter_by(is_active=True).order_by(Account.code).all()


def header_ids(accounts=None):
    """Ids of the HEADER accounts among *accounts* (default: every active account): those that are some active
    account's parent."""
    accounts = active_accounts() if accounts is None else accounts
    ids = {a.id for a in accounts}
    return {a.parent_id for a in accounts if a.parent_id is not None and a.parent_id in ids}


def postable_accounts(account_type=None, accounts=None):
    """Active postable accounts, code order; optionally of one account_type."""
    accounts = active_accounts() if accounts is None else accounts
    heads = header_ids(accounts)
    return [a for a in accounts
            if a.id not in heads and (account_type is None or a.account_type == account_type)]


def picker_rows(accounts=None):
    """Every active account as `to_dict()` plus `is_group` (a header: shown, not selectable) and `depth` (for the
    indent) -- the voucher forms' account picker. Its non-group ids are also those forms' server-side allowlist."""
    accounts = active_accounts() if accounts is None else accounts
    heads = header_ids(accounts)
    by_id = {a.id: a for a in accounts}

    def depth(acct):
        d, p, seen = 0, acct.parent_id, set()
        while p and p in by_id and p not in seen:
            seen.add(p)
            d += 1
            p = by_id[p].parent_id
        return d

    rows = []
    for a in accounts:
        row = a.to_dict()
        row['is_group'] = a.id in heads
        row['depth'] = depth(a)
        rows.append(row)
    return rows


def postable_choices(placeholder, none_value=0, sep=' : '):
    """[(none_value, placeholder), (id, 'code : name'), ...] over the postable accounts -- the tax pickers' choices."""
    return [(none_value, placeholder)] + [(a.id, f'{a.code}{sep}{a.name}') for a in postable_accounts()]
