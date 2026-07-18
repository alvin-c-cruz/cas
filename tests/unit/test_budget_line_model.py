"""BudgetLine: flat matrix of (branch, account, fiscal_year, month) -> amount.
No header table -- see docs/superpowers/specs/2026-07-19-budgeting-entry-r09-slice1-design.md.
"""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.accounts.models import Account
from app.branches.models import Branch
from app.budgeting.models import BudgetLine


def _make_branch(db_session, code='MAIN'):
    b = Branch(code=code, name='Main Office', is_active=True)
    db_session.add(b)
    db_session.commit()
    return b


def _make_account(db_session, code='4001', account_type='Revenue'):
    a = Account(code=code, name=f'Account {code}', account_type=account_type,
                normal_balance='Credit' if account_type == 'Revenue' else 'Debit',
                is_active=True)
    db_session.add(a)
    db_session.commit()
    return a


def test_budget_line_create(db_session):
    branch = _make_branch(db_session)
    account = _make_account(db_session)
    line = BudgetLine(branch_id=branch.id, account_id=account.id,
                       fiscal_year=2027, month=1, amount=Decimal('15000.00'))
    db_session.add(line)
    db_session.commit()

    saved = BudgetLine.query.first()
    assert saved.amount == Decimal('15000.00')
    assert saved.month == 1
    assert saved.fiscal_year == 2027
    assert saved.branch_id == branch.id
    assert saved.account_id == account.id


def test_budget_line_unique_branch_account_year_month(db_session):
    branch = _make_branch(db_session)
    account = _make_account(db_session)
    db_session.add(BudgetLine(branch_id=branch.id, account_id=account.id,
                              fiscal_year=2027, month=1, amount=Decimal('1000')))
    db_session.commit()

    db_session.add(BudgetLine(branch_id=branch.id, account_id=account.id,
                              fiscal_year=2027, month=1, amount=Decimal('2000')))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_budget_line_same_account_different_month_allowed(db_session):
    branch = _make_branch(db_session)
    account = _make_account(db_session)
    db_session.add(BudgetLine(branch_id=branch.id, account_id=account.id,
                              fiscal_year=2027, month=1, amount=Decimal('1000')))
    db_session.add(BudgetLine(branch_id=branch.id, account_id=account.id,
                              fiscal_year=2027, month=2, amount=Decimal('1100')))
    db_session.commit()  # must not raise

    assert BudgetLine.query.filter_by(branch_id=branch.id, account_id=account.id,
                                      fiscal_year=2027).count() == 2
