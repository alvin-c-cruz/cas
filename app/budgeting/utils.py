"""Helpers for the Budget Entry grid (R-09 Slice 1).

Only active, postable (leaf) Revenue/Expense accounts are budgetable. Hierarchy is
derived, not stored -- mirrors app/accounts/views.py::list_accounts's DFS ordering
and app/opening_balances/utils.py's leaf-account convention. Account.base_category
is a plain Python property (not a SQL expression), so eligibility is computed after
loading, not filtered in the query.
"""
from decimal import Decimal, InvalidOperation

from app.accounts.models import Account

ELIGIBLE_BASE_CATEGORIES = ('Revenue', 'Expense')

MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December']


def account_tree_index(accounts):
    """Build the parent/child index used by every COA-tree walk in this app (mirrors
    app/accounts/views.py::list_accounts's DFS prologue). `accounts` must already be
    code-sorted. Returns (id_to_account, has_children, children_by_parent, roots)."""
    id_to_account = {a.id: a for a in accounts}
    has_children = {a.parent_id for a in accounts if a.parent_id}
    children_by_parent = {}
    roots = []
    for a in accounts:
        if a.parent_id and a.parent_id in id_to_account:
            children_by_parent.setdefault(a.parent_id, []).append(a)
        else:
            roots.append(a)
    return id_to_account, has_children, children_by_parent, roots


def budget_account_rows():
    """Pre-order DFS rows for the grid template: every header (shown for grouping
    context, same as the Chart of Accounts list) plus every active, postable
    Revenue/Expense leaf. Non-eligible leaves (Asset/Liability/Equity, or inactive)
    are omitted entirely -- no blank rows.

    Returns a list of {'account': Account, 'depth': int, 'is_header': bool}.
    """
    accounts = Account.query.order_by(Account.code).all()
    id_to_account, has_children, children_by_parent, roots = account_tree_index(accounts)

    rows = []
    visited = set()

    def walk(node, depth):
        if node.id in visited:
            return
        visited.add(node.id)
        is_header = node.id in has_children or node.parent_id is None
        eligible_leaf = (not is_header and node.is_active
                         and node.base_category in ELIGIBLE_BASE_CATEGORIES)
        if is_header or eligible_leaf:
            rows.append({'account': node, 'depth': depth, 'is_header': is_header})
        for child in children_by_parent.get(node.id, []):
            walk(child, depth + 1)

    for r in roots:
        walk(r, 0)
    return rows


def budget_eligible_account_ids():
    """Ids of active, postable Revenue/Expense accounts -- the server-side allowlist
    for the grid's editable cells (same set budget_account_rows() renders as
    non-header rows)."""
    return {row['account'].id for row in budget_account_rows() if not row['is_header']}


def to_decimal(raw):
    """Parse a grid cell's raw string into a Decimal, defaulting blank/invalid to 0.
    Does not reject negatives -- that check belongs to the caller (the save view),
    since a helper for both display and parsing shouldn't bake in one call site's
    validation rule."""
    try:
        return Decimal(str(raw or '0').replace(',', '').strip() or '0')
    except (InvalidOperation, ValueError):
        return Decimal('0')
