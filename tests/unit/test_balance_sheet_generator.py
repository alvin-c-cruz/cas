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


def _acct(code, name, atype, normal='debit', classification=None):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal,
                is_active=True, classification=classification)
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


def test_current_vs_noncurrent_divisions(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'debit', classification='Current')
    mach = _acct('11120', 'Machinery', 'Asset', 'debit', classification='Non-Current')
    ap   = _acct('20101', 'AP - Trade', 'Liability', 'credit', classification='Current')
    loan = _acct('21100', 'Long-term Loan', 'Liability', 'credit', classification='Non-Current')
    cap  = _acct('30101', 'Common Stock', 'Equity', 'credit')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE-1')
    _je(b.id, [(mach, 500, 0), (loan, 0, 500)], 'JE-2')
    _je(b.id, [(cash, 0, 200), (ap, 0, 200)], 'JE-3')  # AP credit 200, cash down 200
    bs = generate_balance_sheet(date(2026, 6, 30), b.id)
    assets = next(s for s in bs['sections'] if s['key'] == 'assets')
    divs = {d['label']: d for d in assets['divisions']}
    assert set(divs) == {'Current Assets', 'Non-Current Assets'}
    assert divs['Current Assets']['total'] == 800.0       # cash 1000 - 200
    assert divs['Non-Current Assets']['total'] == 500.0
    liabs = next(s for s in bs['sections'] if s['key'] == 'liabilities')
    ldivs = {d['label']: d['total'] for d in liabs['divisions']}
    assert ldivs == {'Current Liabilities': 200.0, 'Non-Current Liabilities': 500.0}


def test_balanced(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'debit', classification='Current')
    cap  = _acct('30101', 'Common Stock', 'Equity', 'credit')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE-1')
    bs = generate_balance_sheet(date(2026, 6, 30), b.id)
    assert bs['is_balanced'] is True
    assert bs['total_assets'] == bs['total_liabilities_equity'] == 1000.0
