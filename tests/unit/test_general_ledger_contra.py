from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_general_ledger

pytestmark = [pytest.mark.unit]


def _branch():
    b = Branch(name='Main', code='MAIN')
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype='Asset', normal='Debit'):
    a = Account(code=code, name=name, account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


def _entry(branch_id, when, number, lines):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=when, description='d', reference=number,
                      entry_type='adjustment', branch_id=branch_id, status='posted',
                      is_balanced=True, total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=acct.id,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr)),
                                        description=f'{number} l{n}'))
        n += 1
    db.session.commit()
    return je


def _line_for(gl, code):
    sec = next(a for a in gl['accounts'] if a['code'] == code)
    return sec['lines'][0]


def test_two_line_entry_contra_is_other_account_name(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    sales = _acct('4001', 'Sales Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 100, 0), (sales, 0, 100)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _line_for(gl, '1001')['contra'] == 'Sales Revenue'
    assert _line_for(gl, '4001')['contra'] == 'Cash'


def test_multi_contra_is_various_single_opposite_is_named(db_session):
    b = _branch()
    expense = _acct('5001', 'Office Supplies', 'Expense', 'Debit')
    ap = _acct('2001', 'Accounts Payable', 'Liability', 'Credit')
    wht = _acct('2002', 'WHT Payable', 'Liability', 'Credit')
    # Dr Expense 100 / Cr AP 88 / Cr WHT 12
    _entry(b.id, date(2026, 6, 7), 'JE-2', [(expense, 100, 0), (ap, 0, 88), (wht, 0, 12)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert _line_for(gl, '5001')['contra'] == 'Various'      # opposite = AP + WHT
    assert _line_for(gl, '2001')['contra'] == 'Office Supplies'  # opposite = Expense only
    assert _line_for(gl, '2002')['contra'] == 'Office Supplies'


def test_contra_excludes_own_account_when_on_both_sides(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    # A JE that debits AND credits the same account (self-referential entry)
    _entry(b.id, date(2026, 6, 8), 'JE-SELF', [(cash, 50, 0), (cash, 0, 50)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    sec = next(a for a in gl['accounts'] if a['code'] == '1001')
    # Both lines' only opposite-side account is Cash itself, which must be excluded
    assert all(l['contra'] == '' for l in sec['lines'])
