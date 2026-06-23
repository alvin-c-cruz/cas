from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_cash_flow, _activity_bucket

pytestmark = [pytest.mark.unit]


def _a(code, atype, name='x', cls=None):
    return Account(code=code, name=name, account_type=atype, classification=cls,
                   normal_balance='debit')


def test_activity_bucket_by_type_and_classification():
    assert _activity_bucket(_a('11120', 'Asset', 'Machinery', 'Non-Current')) == 'investing'
    assert _activity_bucket(_a('11131', 'Asset', 'Accumulated Depreciation - Machinery',
                               'Non-Current')) == 'operating'
    assert _activity_bucket(_a('21100', 'Liability', 'Long-term Loan', 'Non-Current')) == 'financing'
    assert _activity_bucket(_a('30101', 'Equity', 'Common Stock')) == 'financing'
    assert _activity_bucket(_a('10201', 'Asset', 'AR - Trade', 'Current')) == 'operating'
    assert _activity_bucket(_a('20101', 'Liability', 'AP - Trade', 'Current')) == 'operating'
    assert _activity_bucket(_a('50101', 'Cost of Goods Sold', 'COGS')) == 'operating'

START, END = date(2026, 1, 1), date(2026, 6, 30)


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype, normal='Debit', parent=None, cls=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent.id if parent else None,
                classification=cls)
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
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset', cls='Current')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca, cls='Current')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca, cls='Current')
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset', cls='Non-Current')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca, cls='Non-Current')
    accum = _acct('11111', 'Accumulated Depreciation', 'Asset', 'Credit', parent=nca,
                  cls='Non-Current')
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit', cls='Current')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl, cls='Current')
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    dep = _acct('50260', 'Depreciation Expense', 'Administrative Expense')
    sal = _acct('50110', 'Salaries Expense', 'Administrative Expense')
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
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset', cls='Current')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca, cls='Current')
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(b.id, [(ar, 100, 0), (rev, 0, 100)], 'CF1')
    cf = generate_cash_flow(START, END, branch_id=b.id)
    assert cf['cash_begin'] == 0.0
    assert cf['cash_end'] == 0.0
    assert cf['net_change'] == 0.0
    assert cf['is_reconciled'] is True


def _build_direct(db_session):
    b = _branch()
    ca = _acct('10000', 'CURRENT ASSETS', 'Asset', cls='Current')
    cash = _acct('10101', 'Cash on Hand', 'Asset', parent=ca, cls='Current')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', parent=ca, cls='Current')
    nca = _acct('11000', 'NON-CURRENT ASSETS', 'Asset', cls='Non-Current')
    equip = _acct('11110', 'Construction Equipment', 'Asset', parent=nca, cls='Non-Current')
    cl = _acct('20000', 'CURRENT LIABILITIES', 'Liability', 'Credit', cls='Current')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'Credit', parent=cl, cls='Current')
    eq = _acct('30000', 'EQUITY', 'Equity', 'Credit')
    cap = _acct('30101', 'Capital Stock', 'Equity', 'Credit', parent=eq)
    rev = _acct('40101', 'Sales Revenue', 'Revenue', 'Credit')
    _je(b.id, [(equip, 2000, 0), (cap, 0, 2000)], 'D1')   # NON-CASH equipment-for-stock
    _je(b.id, [(cash, 500, 0), (rev, 0, 500)], 'D2')      # cash sale -> received from customers +500
    _je(b.id, [(ar, 300, 0), (rev, 0, 300)], 'D3')        # credit sale (non-cash) -> excluded
    _je(b.id, [(cash, 200, 0), (ar, 0, 200)], 'D4')       # collection -> received from customers +200
    _je(b.id, [(ap, 150, 0), (cash, 0, 150)], 'D5')       # pay supplier -> paid to suppliers -150
    return b


def test_direct_reconciles(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    assert cf['method'] == 'direct'
    assert cf['cash_end'] == 550.0 and cf['cash_begin'] == 0.0
    assert cf['net_change'] == 550.0
    assert cf['is_reconciled'] is True


def test_direct_sections_are_cash_only(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    # non-cash equipment-for-stock is excluded from the sections, shown in the note
    assert cf['investing']['lines'] == []
    assert cf['investing']['total'] == 0.0
    assert cf['financing']['lines'] == []
    assert cf['financing']['total'] == 0.0
    assert any(n['amount'] == 2000.0 for n in cf['noncash'])


def test_direct_operating_sublines(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    lines = {l['name']: l['amount'] for l in cf['operating']['lines']}
    assert lines['Cash received from customers'] == 700.0     # 500 sale + 200 collection
    assert lines['Cash paid to suppliers'] == -150.0
    assert cf['operating']['total'] == 550.0


def test_direct_reconciliation_note(db_session):
    b = _build_direct(db_session)
    cf = generate_cash_flow(START, END, branch_id=b.id, method='direct')
    rec = cf['reconciliation']
    assert rec['net_income'] == 800.0                          # revenue 500 + 300, no expense
    assert rec['total'] == cf['operating']['total']            # foots to operating cash (550)


def test_direct_guard_and_indirect_unchanged(db_session):
    b = _build_direct(db_session)
    with pytest.raises(ValueError):
        generate_cash_flow(START, END, branch_id=b.id, method='xyz')
    ind = generate_cash_flow(START, END, branch_id=b.id, method='indirect')
    assert ind['method'] == 'indirect'
    assert 'noncash' not in ind and 'reconciliation' not in ind
    assert set(ind['operating'].keys()) == {'net_income', 'depreciation', 'working_capital', 'total'}
