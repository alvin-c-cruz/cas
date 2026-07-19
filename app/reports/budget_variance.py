"""Budget-vs-Actual Variance Report (R-09 Slice 2). Read-only -- reuses
_period_balance for Actual and sums BudgetLine for Budget. See
docs/superpowers/specs/2026-07-19-budget-variance-report-r09-slice2-design.md.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from app.accounts.models import Account
from app.accounts.account_types import DEFAULT_NORMAL_BALANCE, BASE_CATEGORY
from app.budgeting.models import BudgetLine
from app.budgeting.utils import account_tree_index
from app.reports.financial import _period_balance

ELIGIBLE_BASE_CATEGORIES = ('Revenue', 'Expense')


def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _signed_actual(account, debit, credit):
    normal = DEFAULT_NORMAL_BALANCE.get(account.account_type)
    return float((credit - debit) if normal == 'credit' else (debit - credit))


def _variance(base_category, budget, actual):
    return (actual - budget) if base_category == 'Revenue' else (budget - actual)


def _variance_pct(variance, budget):
    if budget == 0:
        return None
    return round(variance / budget * 100, 2)


def generate_budget_variance(branch_id, fiscal_year, month):
    """Budget vs Actual for every Revenue/Expense account with a budget or actual
    GL activity, for `month` of `fiscal_year` (MTD) and Jan 1..month-end (YTD),
    scoped to `branch_id`. Deactivated accounts with historical data still show
    -- this is a historical report, not a forward-entry surface."""
    mtd_start, mtd_end = _month_bounds(fiscal_year, month)
    ytd_start = date(fiscal_year, 1, 1)

    accounts = Account.query.order_by(Account.code).all()
    id_to_account, has_children, children_by_parent, roots = account_tree_index(accounts)

    budget_lines = BudgetLine.query.filter(
        BudgetLine.branch_id == branch_id, BudgetLine.fiscal_year == fiscal_year,
        BudgetLine.month <= month).all()
    mtd_budget_by_account = {}
    ytd_budget_by_account = {}
    for bl in budget_lines:
        ytd_budget_by_account[bl.account_id] = (
            ytd_budget_by_account.get(bl.account_id, Decimal('0')) + bl.amount)
        if bl.month == month:
            mtd_budget_by_account[bl.account_id] = bl.amount

    def leaf_row(account):
        base_cat = BASE_CATEGORY.get(account.account_type, account.account_type)
        if base_cat not in ELIGIBLE_BASE_CATEGORIES:
            return None
        mtd_budget = float(mtd_budget_by_account.get(account.id, Decimal('0')))
        ytd_budget = float(ytd_budget_by_account.get(account.id, Decimal('0')))
        mtd_d, mtd_c = _period_balance(account.id, mtd_start, mtd_end, branch_id)
        ytd_d, ytd_c = _period_balance(account.id, ytd_start, mtd_end, branch_id)
        mtd_actual = _signed_actual(account, mtd_d, mtd_c)
        ytd_actual = _signed_actual(account, ytd_d, ytd_c)
        if mtd_budget == 0 and ytd_budget == 0 and mtd_actual == 0 and ytd_actual == 0:
            return None  # not in scope: no budget, no activity
        mtd_variance = _variance(base_cat, mtd_budget, mtd_actual)
        ytd_variance = _variance(base_cat, ytd_budget, ytd_actual)
        return {
            'account': account, 'is_header': False,
            'mtd_budget': mtd_budget, 'mtd_actual': mtd_actual,
            'mtd_variance': mtd_variance, 'mtd_variance_pct': _variance_pct(mtd_variance, mtd_budget),
            'ytd_budget': ytd_budget, 'ytd_actual': ytd_actual,
            'ytd_variance': ytd_variance, 'ytd_variance_pct': _variance_pct(ytd_variance, ytd_budget),
        }

    visited = set()

    def build(node, depth):
        if node.id in visited:
            return []
        visited.add(node.id)
        is_header = node.id in has_children or node.parent_id is None
        if not is_header:
            row = leaf_row(node)
            if row is None:
                return []
            row['depth'] = depth
            return [row]
        child_rows = []
        for child in children_by_parent.get(node.id, []):
            child_rows.extend(build(child, depth + 1))
        if not child_rows:
            return []
        return [{'account': node, 'depth': depth, 'is_header': True}] + child_rows

    rows = []
    for r in roots:
        rows.extend(build(r, 0))

    return {
        'fiscal_year': fiscal_year, 'month': month,
        'month_label': date(fiscal_year, month, 1).strftime('%B %Y'),
        'mtd_start': mtd_start, 'mtd_end': mtd_end, 'ytd_start': ytd_start,
        'rows': rows,
    }
