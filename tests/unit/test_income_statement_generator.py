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


def _acct(code, name, atype, normal='Debit', parent_id=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, parent_id=parent_id)
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
    cash = _acct('10101', 'Cash', 'Asset')
    g_rev = _acct('40000', 'REVENUE', 'Revenue', 'Credit')
    rev = _acct('40101', 'Construction Contract Revenue', 'Revenue', 'Credit', parent_id=g_rev.id)
    g_cos = _acct('50100', 'Cost of Construction', 'Expense')
    cos = _acct('50101', 'Direct Materials', 'Expense', parent_id=g_cos.id)
    g_opex = _acct('50200', 'Operating Expenses', 'Expense')
    opex = _acct('50210', 'Salaries and Wages', 'Expense', parent_id=g_opex.id)
    g_fin = _acct('50300', 'Financial Expenses', 'Expense')
    fin = _acct('50301', 'Interest Expense', 'Expense', parent_id=g_fin.id)
    g_tax = _acct('50400', 'Income Tax Expense', 'Expense')
    tax = _acct('50401', 'Income Tax Expense - Current', 'Expense', parent_id=g_tax.id)
    # Revenue 1000, Cost 400, Opex 200, Financial 50, Tax 90
    _je(b.id, [(cash, 1000, 0), (rev, 0, 1000)], 'JE-R')
    _je(b.id, [(cos, 400, 0), (cash, 0, 400)], 'JE-C')
    _je(b.id, [(opex, 200, 0), (cash, 0, 200)], 'JE-O')
    _je(b.id, [(fin, 50, 0), (cash, 0, 50)], 'JE-F')
    _je(b.id, [(tax, 90, 0), (cash, 0, 90)], 'JE-T')
    return b


def test_section_totals_and_labels(db_session):
    b = _full_pl(db_session)
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _section(stmt, 'revenue')['total'] == 1000.0
    assert _section(stmt, 'revenue')['label'] == 'REVENUE'
    assert _section(stmt, 'cost_of_sales')['total'] == 400.0
    assert _section(stmt, 'cost_of_sales')['label'] == 'Cost of Construction'
    assert _section(stmt, 'operating_expenses')['total'] == 200.0
    assert _section(stmt, 'financial')['total'] == 50.0
    assert _section(stmt, 'income_tax')['total'] == 90.0
    # children present under their section
    assert [a['code'] for a in _section(stmt, 'cost_of_sales')['accounts']] == ['50101']


def test_subtotals(db_session):
    b = _full_pl(db_session)
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert stmt['gross_profit'] == 600.0            # 1000 - 400
    assert stmt['operating_income'] == 400.0        # 600 - 200
    assert stmt['income_before_tax'] == 350.0       # 400 - 50
    assert stmt['net_income'] == 260.0              # 350 - 90


def test_zero_activity_accounts_excluded(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset')
    g_rev = _acct('40000', 'REVENUE', 'Revenue', 'Credit')
    rev = _acct('40101', 'Contract Revenue', 'Revenue', 'Credit', parent_id=g_rev.id)
    _acct('40102', 'Service Income', 'Revenue', 'Credit', parent_id=g_rev.id)  # no activity
    _je(b.id, [(cash, 500, 0), (rev, 0, 500)], 'JE-R')
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    codes = [a['code'] for a in _section(stmt, 'revenue')['accounts']]
    assert codes == ['40101']                        # 40102 excluded (zero), parent 40000 excluded


def test_missing_income_tax_account_yields_zero_section(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset')
    g_rev = _acct('40000', 'REVENUE', 'Revenue', 'Credit')
    rev = _acct('40101', 'Contract Revenue', 'Revenue', 'Credit', parent_id=g_rev.id)
    g_cos = _acct('50100', 'Cost of Construction', 'Expense')
    cos = _acct('50101', 'Direct Materials', 'Expense', parent_id=g_cos.id)
    _je(b.id, [(cash, 1000, 0), (rev, 0, 1000)], 'JE-R')
    _je(b.id, [(cos, 400, 0), (cash, 0, 400)], 'JE-C')
    stmt = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _section(stmt, 'income_tax')['total'] == 0.0
    assert _section(stmt, 'income_tax')['accounts'] == []
    assert stmt['net_income'] == 600.0               # 1000 - 400, no tax/opex/financial
    assert stmt['net_income'] == stmt['income_before_tax'] == stmt['operating_income']
