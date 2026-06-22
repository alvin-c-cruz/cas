from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_cash_flow

pytestmark = [pytest.mark.unit]

START, END = date(2026, 1, 1), date(2026, 6, 30)


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
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca)
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca)
    accum = _acct('11111', 'Accumulated Depreciation', 'Asset', 'Credit', parent=nca)
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl)
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    dep = _acct('50260', 'Depreciation Expense', 'Expense')
    sal = _acct('50110', 'Salaries Expense', 'Expense')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'CF1')   # financing inflow 1000, cash +1000
    _je(b.id, [(equip, 500, 0), (cash, 0, 500)], 'CF2')   # investing outflow -500, cash -500
    _je(b.id, [(cash, 200, 0), (rev, 0, 200)], 'CF3')     # NI +200, cash +200
    _je(b.id, [(dep, 50, 0), (accum, 0, 50)], 'CF4')      # NI -50, depreciation add-back +50
    _je(b.id, [(ar, 300, 0), (rev, 0, 300)], 'CF5')       # NI +300, AR up -> WC -300
    _je(b.id, [(sal, 100, 0), (ap, 0, 100)], 'CF6')       # NI -100, AP up -> WC +100
    return b


def test_reconciles(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['cash_begin'] == 0.0
    assert cf['cash_end'] == 700.0
    assert cf['net_change'] == 700.0
    assert cf['is_reconciled'] is True
    assert cf['difference'] == 0.0


def test_operating(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    op = cf['operating']
    assert op['net_income'] == 350.0          # (200+300) - (50+100)
    assert op['depreciation'] == 50.0
    assert op['total'] == 200.0               # 350 + 50 - 200
    wc = {w['amount'] for w in op['working_capital']}
    assert -300.0 in wc                        # AR increase consumes cash
    assert 100.0 in wc                         # AP increase frees cash


def test_depreciation_excluded_from_investing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert all('Accumulated Depreciation' not in ln['name'] for ln in cf['investing']['lines'])


def test_investing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['investing']['total'] == -500.0
    assert any(ln['amount'] == -500.0 for ln in cf['investing']['lines'])


def test_financing(db_session):
    b = _build(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['financing']['total'] == 1000.0
    assert any(ln['name'] == 'Capital Stock' and ln['amount'] == 1000.0
               for ln in cf['financing']['lines'])


def test_no_cash_accounts(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(b.id, [(ar, 100, 0), (rev, 0, 100)], 'CF1')
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['cash_begin'] == 0.0
    assert cf['cash_end'] == 0.0
    assert cf['net_change'] == 0.0
    assert cf['is_reconciled'] is True


def test_rejects_direct_method(db_session):
    b = _build(db_session)
    with pytest.raises(ValueError):
        generate_cash_flow(START, END, branch_id=b.id, method='direct')
