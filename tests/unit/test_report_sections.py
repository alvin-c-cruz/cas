import pytest
from app import db
from app.accounts.models import Account
from app.reports.sections import IS_SECTIONS, BS_SECTIONS, rollup

pytestmark = [pytest.mark.unit]

def test_is_sections_cover_all_is_types():
    from app.accounts.account_types import IS_TYPES
    covered = [t for s in IS_SECTIONS for t in s['types']]
    assert covered == IS_TYPES
    # subtotal chain present in order
    subs = [s['subtotal'] for s in IS_SECTIONS if s['subtotal']]
    assert subs == ['Net Sales', 'Gross Profit', 'Operating Income',
                    'Income Before Tax', 'Net Income']

def test_bs_sections():
    keys = [s['key'] for s in BS_SECTIONS]
    assert keys == ['assets', 'liabilities', 'equity']
    assets = next(s for s in BS_SECTIONS if s['key'] == 'assets')
    assert assets['divisions'] == ['Current', 'Non-Current']
    assert next(s for s in BS_SECTIONS if s['key'] == 'equity')['divisions'] is None

def test_rollup_groups_children_under_parent(db_session):
    p = Account(code='50220', name='G&A', account_type='Administrative Expense',
                normal_balance='debit', is_active=True)
    db.session.add(p); db.session.commit()
    c1 = Account(code='50221', name='Office Salaries', account_type='Administrative Expense',
                 normal_balance='debit', is_active=True, parent_id=p.id)
    c2 = Account(code='50224', name='Office Rent', account_type='Administrative Expense',
                 normal_balance='debit', is_active=True, parent_id=p.id)
    db.session.add_all([c1, c2]); db.session.commit()
    accounts = Account.query.all()
    rows = [{'account_id': c1.id, 'code': '50221', 'name': 'Office Salaries', 'amount': 100.0},
            {'account_id': c2.id, 'code': '50224', 'name': 'Office Rent', 'amount': 50.0}]
    lines = rollup(rows, accounts)
    assert len(lines) == 1
    assert lines[0]['code'] == '50220'
    assert lines[0]['total'] == 150.0
    assert {ch['code'] for ch in lines[0]['children']} == {'50221', '50224'}

def test_rollup_orphan_leaf_is_its_own_line(db_session):
    a = Account(code='50101', name='COGS', account_type='Cost of Goods Sold',
                normal_balance='debit', is_active=True)
    db.session.add(a); db.session.commit()
    rows = [{'account_id': a.id, 'code': '50101', 'name': 'COGS', 'amount': 400.0}]
    lines = rollup(rows, Account.query.all())
    assert lines == [{'code': '50101', 'name': 'COGS', 'account_id': a.id,
                      'total': 400.0, 'children': []}]

def test_rollup_walks_past_mid_level_to_top(db_session):
    """A 3-deep chain (leaf -> mid -> top) must roll the leaf up to the TOP
    ancestor, not the mid-level parent."""
    top = Account(code='50200', name='Operating Expenses',
                  account_type='Administrative Expense', normal_balance='debit', is_active=True)
    db.session.add(top); db.session.commit()
    mid = Account(code='50220', name='G&A', account_type='Administrative Expense',
                  normal_balance='debit', is_active=True, parent_id=top.id)
    db.session.add(mid); db.session.commit()
    leaf = Account(code='50221', name='Office Salaries', account_type='Administrative Expense',
                   normal_balance='debit', is_active=True, parent_id=mid.id)
    db.session.add(leaf); db.session.commit()
    rows = [{'account_id': leaf.id, 'code': '50221', 'name': 'Office Salaries', 'amount': 100.0}]
    lines = rollup(rows, Account.query.all())
    assert len(lines) == 1
    assert lines[0]['code'] == '50200'           # rolled up to TOP, not mid (50220)
    assert lines[0]['total'] == 100.0
    assert [ch['code'] for ch in lines[0]['children']] == ['50221']
