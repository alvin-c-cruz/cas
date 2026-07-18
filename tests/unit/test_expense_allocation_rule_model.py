import pytest
from app import db
from app.accounts.models import Account
from app.expense_allocation_rules.models import ExpenseAllocationRule

pytestmark = [pytest.mark.unit]


def _account():
    a = Account(code='52201', name='Office Supplies', account_type='Administrative Expense',
                normal_balance='debit', is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


def test_create_rule(db_session):
    a = _account()
    r = ExpenseAllocationRule(account_id=a.id, basis='revenue_share')
    db.session.add(r)
    db.session.commit()
    fetched = db.session.get(ExpenseAllocationRule, r.id)
    assert fetched.account_id == a.id
    assert fetched.basis == 'revenue_share'


def test_account_id_unique(db_session):
    a = _account()
    db.session.add(ExpenseAllocationRule(account_id=a.id, basis='equal'))
    db.session.commit()
    db.session.add(ExpenseAllocationRule(account_id=a.id, basis='none'))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_to_dict(db_session):
    a = _account()
    r = ExpenseAllocationRule(account_id=a.id, basis='units_sold')
    db.session.add(r)
    db.session.commit()
    d = r.to_dict()
    assert d['account_id'] == a.id
    assert d['account_code'] == '52201'
    assert d['account_name'] == 'Office Supplies'
    assert d['basis'] == 'units_sold'
