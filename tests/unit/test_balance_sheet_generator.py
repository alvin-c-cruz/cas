from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_balance_sheet

pytestmark = [pytest.mark.unit]


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype, normal='Debit', parent=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None)
    db.session.add(a)
    db.session.commit()
    return a


def _je(branch_id, lines, number):
    je = JournalEntry(entry_number=number, entry_date=date(2026, 6, 10), description='d',
                      reference=number, entry_type='adjustment', branch_id=branch_id,
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


def _build(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca)
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')   # drives Net Income (YTD)
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE1')           # assets 1000 / equity 1000
    _je(b.id, [(equip, 500, 0), (ap, 0, 500)], 'JE2')            # assets 500 / liab 500
    _je(b.id, [(cash, 200, 0), (rev, 0, 200)], 'JE3')            # cash +200 / revenue 200 -> NI 200
    return b


def _section(bs, key):
    return next(s for s in bs['sections'] if s['key'] == key)


def test_classified_groups_and_totals(db_session):
    b = _build(db_session)
    bs = generate_balance_sheet(date(2026, 6, 30), branch_id=b.id)
    assets = _section(bs, 'assets')
    groups = {g['label']: g for g in assets['groups']}
    assert groups['Current Assets']['total'] == 1200.0       # 1000 + 200
    assert groups['Non-Current Assets']['total'] == 500.0
    assert assets['total'] == 1700.0
    assert _section(bs, 'liabilities')['total'] == 500.0


def test_equity_includes_net_income_ytd(db_session):
    b = _build(db_session)
    bs = generate_balance_sheet(date(2026, 6, 30), branch_id=b.id)
    equity = _section(bs, 'equity')
    accts = equity['groups'][0]['accounts']
    assert any(a['name'] == 'Capital Stock' and a['amount'] == 1000.0 for a in accts)
    assert any(a['name'] == 'Net Income (current year)' and a['amount'] == 200.0 for a in accts)
    assert equity['total'] == 1200.0                          # 1000 capital + 200 net income


def test_balance_sheet_balances(db_session):
    b = _build(db_session)
    bs = generate_balance_sheet(date(2026, 6, 30), branch_id=b.id)
    assert bs['total_assets'] == 1700.0
    assert bs['total_liabilities_equity'] == 1700.0           # 500 + 1200
    assert bs['is_balanced'] is True
    assert bs['difference'] == 0.0


def test_empty_groups_omitted(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    _acct('11110', 'Construction Equipment', 'Asset', parent=nca)  # no activity
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE1')
    bs = generate_balance_sheet(date(2026, 6, 30), branch_id=b.id)
    labels = [g['label'] for g in _section(bs, 'assets')['groups']]
    assert labels == ['Current Assets']                       # Non-Current omitted (no non-zero accounts)
