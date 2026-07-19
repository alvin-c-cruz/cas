"""generate_budget_variance: read-only Budget-vs-Actual, MTD + YTD. See
docs/superpowers/specs/2026-07-19-budget-variance-report-r09-slice2-design.md.
"""
from datetime import date
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.budgeting.models import BudgetLine
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.budget_variance import generate_budget_variance


def _branch(code='MAIN'):
    b = Branch(name='Main', code=code)
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, account_type, normal_balance, parent_id=None, is_active=True):
    a = Account(code=code, name=name, account_type=account_type, normal_balance=normal_balance,
                is_active=is_active, parent_id=parent_id)
    db.session.add(a)
    db.session.commit()
    return a


def _revenue_leaf(code='4001', name='Sales Revenue', is_active=True):
    # Top-level accounts are ALWAYS headers under the derived-hierarchy rule -- a leaf fixture
    # needs an explicit parent group, unlike generate_income_statement's own tests (which don't
    # care about hierarchy at all).
    group = _acct('4000', 'Revenue', 'Revenue', 'credit')
    return _acct(code, name, 'Revenue', 'credit', parent_id=group.id, is_active=is_active)


def _expense_leaf(code='5001', name='Office Supplies', is_active=True):
    group = _acct('5000', 'Expenses', 'Administrative Expense', 'debit')
    return _acct(code, name, 'Administrative Expense', 'debit', parent_id=group.id,
                is_active=is_active)


def _je(branch_id, lines, number, entry_date, entry_type='adjustment'):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=entry_date, description='d',
                      reference=number, entry_type=entry_type, branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=Decimal('0'),
                      total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
        n += 1
    db.session.commit()
    return je


def _budget(branch_id, account_id, fiscal_year, month, amount):
    bl = BudgetLine(branch_id=branch_id, account_id=account_id, fiscal_year=fiscal_year,
                    month=month, amount=Decimal(str(amount)))
    db.session.add(bl)
    db.session.commit()
    return bl


def _leaf_rows(data):
    return [r for r in data['rows'] if not r['is_header']]


def _row_for(data, account_id):
    return next(r for r in _leaf_rows(data) if r['account'].id == account_id)


def test_mtd_revenue_favorable_variance(db_session):
    branch = _branch()
    rev = _revenue_leaf()
    _budget(branch.id, rev.id, 2027, 3, 10000)
    _je(branch.id, [(rev, 0, 12000)], 'JE-1', date(2027, 3, 15))  # credit-positive actual

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, rev.id)
    assert row['mtd_budget'] == 10000.0
    assert row['mtd_actual'] == 12000.0
    assert row['mtd_variance'] == 2000.0          # actual - budget, favorable (more revenue)
    assert row['mtd_variance_pct'] == 20.0


def test_mtd_expense_unfavorable_variance(db_session):
    branch = _branch()
    exp = _expense_leaf()
    _budget(branch.id, exp.id, 2027, 3, 5000)
    _je(branch.id, [(exp, 6000, 0)], 'JE-1', date(2027, 3, 20))  # debit-positive actual

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, exp.id)
    assert row['mtd_budget'] == 5000.0
    assert row['mtd_actual'] == 6000.0
    assert row['mtd_variance'] == -1000.0         # budget - actual, unfavorable (overspent)
    assert row['mtd_variance_pct'] == -20.0


def test_ytd_accumulates_across_months_independent_of_mtd(db_session):
    branch = _branch()
    rev = _revenue_leaf()
    _budget(branch.id, rev.id, 2027, 1, 1000)
    _budget(branch.id, rev.id, 2027, 2, 1000)
    _budget(branch.id, rev.id, 2027, 3, 1000)
    _je(branch.id, [(rev, 0, 900)], 'JE-1', date(2027, 1, 10))
    _je(branch.id, [(rev, 0, 900)], 'JE-2', date(2027, 2, 10))
    _je(branch.id, [(rev, 0, 900)], 'JE-3', date(2027, 3, 10))

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, rev.id)
    assert row['mtd_budget'] == 1000.0     # March only
    assert row['mtd_actual'] == 900.0
    assert row['ytd_budget'] == 3000.0     # Jan+Feb+Mar
    assert row['ytd_actual'] == 2700.0


def test_zero_budget_shows_none_variance_pct_not_zerodiv(db_session):
    branch = _branch()
    exp = _expense_leaf()
    _je(branch.id, [(exp, 500, 0)], 'JE-1', date(2027, 3, 5))  # actual, no budget at all

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, exp.id)
    assert row['mtd_budget'] == 0.0
    assert row['mtd_actual'] == 500.0
    assert row['mtd_variance_pct'] is None
    assert row['ytd_variance_pct'] is None


def test_row_included_when_budgeted_but_no_actual(db_session):
    branch = _branch()
    exp = _expense_leaf()
    _budget(branch.id, exp.id, 2027, 3, 2000)

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, exp.id)
    assert row['mtd_budget'] == 2000.0
    assert row['mtd_actual'] == 0.0


def test_row_excluded_when_no_budget_and_no_actual(db_session):
    branch = _branch()
    exp = _expense_leaf()  # never budgeted, never posted to

    data = generate_budget_variance(branch.id, 2027, 3)
    assert all(r['account'].id != exp.id for r in _leaf_rows(data))


def test_deactivated_account_still_shows_historical_row(db_session):
    branch = _branch()
    rev = _revenue_leaf(is_active=True)
    _budget(branch.id, rev.id, 2027, 3, 1000)
    rev.is_active = False
    db.session.commit()

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, rev.id)
    assert row['mtd_budget'] == 1000.0


def test_closing_entries_excluded_from_actual(db_session):
    branch = _branch()
    rev = _revenue_leaf()
    _je(branch.id, [(rev, 0, 5000)], 'JE-1', date(2027, 3, 10))
    _je(branch.id, [(rev, 5000, 0)], 'JE-CLOSE', date(2027, 3, 31), entry_type='closing')

    data = generate_budget_variance(branch.id, 2027, 3)
    row = _row_for(data, rev.id)
    assert row['mtd_actual'] == 5000.0   # the closing entry must not zero this out


def test_header_included_only_when_a_descendant_is_in_scope(db_session):
    branch = _branch()
    rev = _revenue_leaf()  # creates parent group '4000' too, with rev as its only child
    other_group = _acct('6000', 'Unused Group', 'Administrative Expense', 'debit')
    _acct('6001', 'Never Budgeted or Posted', 'Administrative Expense', 'debit',
         parent_id=other_group.id)
    _budget(branch.id, rev.id, 2027, 3, 500)

    data = generate_budget_variance(branch.id, 2027, 3)
    header_codes = {r['account'].code for r in data['rows'] if r['is_header']}
    assert '4000' in header_codes           # has an in-scope leaf -> included
    assert '6000' not in header_codes        # no in-scope leaf -> pruned


def test_month_label_and_bounds(db_session):
    branch = _branch()
    data = generate_budget_variance(branch.id, 2027, 3)
    assert data['month_label'] == 'March 2027'
    assert data['mtd_start'] == date(2027, 3, 1)
    assert data['mtd_end'] == date(2027, 3, 31)
    assert data['ytd_start'] == date(2027, 1, 1)
