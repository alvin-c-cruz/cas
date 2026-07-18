from decimal import Decimal

from app.accounts.models import Account
from app.budgeting.utils import (
    budget_account_rows, budget_eligible_account_ids, to_decimal, MONTH_NAMES,
)


def _acct(db_session, code, account_type, is_active=True, parent_id=None):
    a = Account(code=code, name=f'Account {code}', account_type=account_type,
                normal_balance='Credit' if account_type == 'Revenue' else 'Debit',
                is_active=is_active, parent_id=parent_id)
    db_session.add(a)
    db_session.commit()
    return a


def test_month_names_has_twelve_entries_january_first():
    assert len(MONTH_NAMES) == 12
    assert MONTH_NAMES[0] == 'January'
    assert MONTH_NAMES[11] == 'December'


def test_budget_account_rows_includes_active_revenue_and_expense_leaves(db_session):
    # A top-level account with no parent is always a header (hierarchy is derived --
    # top-level or has-children -> header), matching the real COA convention: a real
    # chart never posts directly to a top-level group. So a "leaf" test fixture must
    # be a CHILD of some header, not a bare top-level account.
    rev_group = _acct(db_session, '4000', 'Revenue')
    rev = _acct(db_session, '4001', 'Revenue', parent_id=rev_group.id)
    exp_group = _acct(db_session, '5000', 'Administrative Expense')
    exp = _acct(db_session, '5001', 'Administrative Expense', parent_id=exp_group.id)
    rows = budget_account_rows()
    leaf_ids = {r['account'].id for r in rows if not r['is_header']}
    assert rev.id in leaf_ids
    assert exp.id in leaf_ids


def test_budget_account_rows_excludes_asset_liability_equity_leaves(db_session):
    asset_group = _acct(db_session, '1000', 'Asset')
    asset = _acct(db_session, '1001', 'Asset', parent_id=asset_group.id)
    liab_group = _acct(db_session, '2000', 'Liability')
    liab = _acct(db_session, '2001', 'Liability', parent_id=liab_group.id)
    equity_group = _acct(db_session, '3000', 'Equity')
    equity = _acct(db_session, '3001', 'Equity', parent_id=equity_group.id)
    rows = budget_account_rows()
    leaf_ids = {r['account'].id for r in rows if not r['is_header']}
    assert asset.id not in leaf_ids
    assert liab.id not in leaf_ids
    assert equity.id not in leaf_ids


def test_budget_account_rows_header_vs_leaf_and_inactive(db_session):
    parent = _acct(db_session, '5000', 'Administrative Expense')
    child = _acct(db_session, '5001', 'Administrative Expense', parent_id=parent.id)
    inactive = _acct(db_session, '5002', 'Administrative Expense', is_active=False,
                     parent_id=parent.id)

    rows = budget_account_rows()
    leaf_ids = {r['account'].id for r in rows if not r['is_header']}
    header_ids = {r['account'].id for r in rows if r['is_header']}

    assert parent.id in header_ids        # has a child -> header, not a leaf
    assert parent.id not in leaf_ids
    assert child.id in leaf_ids           # postable leaf under the header
    assert inactive.id not in leaf_ids    # inactive leaf excluded entirely
    assert inactive.id not in header_ids


def test_budget_eligible_account_ids_matches_leaf_rows(db_session):
    rev_group = _acct(db_session, '4000', 'Revenue')
    rev = _acct(db_session, '4001', 'Revenue', parent_id=rev_group.id)
    asset_group = _acct(db_session, '1000', 'Asset')
    asset = _acct(db_session, '1001', 'Asset', parent_id=asset_group.id)
    ids = budget_eligible_account_ids()
    assert rev.id in ids
    assert asset.id not in ids


def test_to_decimal_parses_and_defaults():
    assert to_decimal('1,500.50') == Decimal('1500.50')
    assert to_decimal('') == Decimal('0')
    assert to_decimal(None) == Decimal('0')
    assert to_decimal('abc') == Decimal('0')
    assert to_decimal('-250.00') == Decimal('-250.00')  # parsing allows it; the view rejects it
