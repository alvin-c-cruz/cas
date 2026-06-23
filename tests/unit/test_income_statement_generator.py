from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_income_statement

pytestmark = [pytest.mark.unit]


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype, normal='debit', parent_id=None, classification=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent_id, classification=classification)
    db.session.add(a)
    db.session.commit()
    return a


def _je(branch_id, lines, number):
    """lines: list of (account, debit, credit)."""
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


def _section(stmt, key):
    return next(s for s in stmt['sections'] if s['key'] == key)


def _full_pl(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset', 'credit')  # normal_balance irrelevant to IS
    sales = _acct('40101', 'Sales - Goods', 'Revenue', 'credit')
    disc  = _acct('40104', 'Sales Discounts', 'Contra-Revenue', 'debit')
    cogs  = _acct('50101', 'Cost of Goods Sold', 'Cost of Goods Sold', 'debit')
    sell  = _acct('50211', 'Sales Commissions', 'Selling Expense', 'debit')
    admin = _acct('50221', 'Office Salaries', 'Administrative Expense', 'debit')
    oinc  = _acct('40201', 'Interest Income', 'Other Income', 'credit')
    oexp  = _acct('50301', 'Interest Expense', 'Other Expense', 'debit')
    tax   = _acct('50401', 'Income Tax - Current', 'Income Tax Expense', 'debit')
    # Sales 1000, Discounts 100, COGS 400, Selling 50, Admin 150, OtherInc 30, OtherExp 20, Tax 60
    _je(b.id, [(cash, 1000, 0), (sales, 0, 1000)], 'JE-S')
    _je(b.id, [(disc, 100, 0), (cash, 0, 100)], 'JE-D')
    _je(b.id, [(cogs, 400, 0), (cash, 0, 400)], 'JE-C')
    _je(b.id, [(sell, 50, 0), (cash, 0, 50)], 'JE-SE')
    _je(b.id, [(admin, 150, 0), (cash, 0, 150)], 'JE-AE')
    _je(b.id, [(cash, 30, 0), (oinc, 0, 30)], 'JE-OI')
    _je(b.id, [(oexp, 20, 0), (cash, 0, 20)], 'JE-OE')
    _je(b.id, [(tax, 60, 0), (cash, 0, 60)], 'JE-T')
    return b


def test_section_totals_and_labels(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    sec = {x['key']: x for x in s['sections']}
    assert sec['revenue']['label'] == 'Sales'
    assert sec['revenue']['total'] == 1000.0
    assert sec['contra_revenue']['total'] == 100.0
    assert sec['cogs']['label'] == 'Cost of Goods Sold'
    assert sec['cogs']['total'] == 400.0
    assert sec['selling']['total'] == 50.0
    assert sec['admin']['total'] == 150.0
    assert sec['other_income']['total'] == 30.0
    assert sec['other_expense']['total'] == 20.0
    assert sec['income_tax']['total'] == 60.0


def test_subtotals(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert s['net_sales'] == 900.0           # 1000 - 100
    assert s['gross_profit'] == 500.0        # 900 - 400
    assert s['operating_income'] == 300.0    # 500 - 50 - 150
    assert s['income_before_tax'] == 310.0   # 300 + 30 - 20
    assert s['net_income'] == 250.0          # 310 - 60


def test_lines_rollup_and_account_id(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cogs = next(x for x in s['sections'] if x['key'] == 'cogs')
    assert cogs['lines'][0]['code'] == '50101'
    assert 'account_id' in cogs['lines'][0]


def test_zero_activity_accounts_excluded(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset')
    rev = _acct('40101', 'Contract Revenue', 'Revenue', 'credit')
    _acct('40102', 'Service Income', 'Revenue', 'credit')  # no activity
    _je(b.id, [(cash, 500, 0), (rev, 0, 500)], 'JE-R')
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    rev_sec = _section(stmt, 'revenue')
    codes = [line['code'] for line in rev_sec['lines']]
    assert '40101' in codes                   # has activity
    assert '40102' not in codes               # zero — excluded


def test_missing_income_tax_account_yields_zero_section(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset')
    rev = _acct('40101', 'Contract Revenue', 'Revenue', 'credit')
    cos = _acct('50101', 'Direct Materials', 'Cost of Goods Sold', 'debit')
    _je(b.id, [(cash, 1000, 0), (rev, 0, 1000)], 'JE-R')
    _je(b.id, [(cos, 400, 0), (cash, 0, 400)], 'JE-C')
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _section(stmt, 'income_tax')['total'] == 0.0
    assert _section(stmt, 'income_tax')['lines'] == []
    assert stmt['net_income'] == 600.0               # 1000 - 400, no tax/opex/financial
    assert stmt['net_income'] == stmt['income_before_tax'] == stmt['operating_income']
