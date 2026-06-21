from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.branches.models import Branch
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import generate_general_ledger

pytestmark = [pytest.mark.unit]


def _branch(name='Main', code='MAIN'):
    b = Branch(name=name, code=code)
    db.session.add(b)
    db.session.commit()
    return b


def _acct(code, name, atype='Asset', normal='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                normal_balance=normal, is_active=True)
    db.session.add(a)
    db.session.commit()
    return a


def _entry(branch_id, entry_date, number, lines, status='posted',
           entry_type='adjustment', reference=None):
    """lines: list of (account, debit, credit)."""
    je = JournalEntry(entry_number=number, entry_date=entry_date,
                      description='desc ' + number, reference=reference or number,
                      entry_type=entry_type, branch_id=branch_id, status=status,
                      is_balanced=True, total_debit=Decimal('0'), total_credit=Decimal('0'))
    db.session.add(je)
    db.session.flush()
    n = 1
    for acct, dr, cr in lines:
        db.session.add(JournalEntryLine(
            entry_id=je.id, line_number=n, account_id=acct.id,
            debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr)),
            description=f'{number} line {n}'))
        n += 1
    je.total_debit = sum((Decimal(str(d)) for _, d, _ in lines), Decimal('0'))
    je.total_credit = sum((Decimal(str(c)) for _, _, c in lines), Decimal('0'))
    db.session.commit()
    return je


def test_opening_balance_sums_only_prior_posted_lines(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    # prior: cash +1000
    _entry(b.id, date(2026, 5, 31), 'JE-1', [(cash, 1000, 0), (rev, 0, 1000)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cash_sec = next(a for a in gl['accounts'] if a['code'] == '1001')
    assert cash_sec['opening_balance'] == 1000.0
    assert cash_sec['lines'] == []  # no in-range movement


def test_running_balance_accumulates_and_equals_closing(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 500, 0), (rev, 0, 500)])
    _entry(b.id, date(2026, 6, 9), 'JE-2', [(cash, 0, 200), (rev, 200, 0)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cash_sec = next(a for a in gl['accounts'] if a['code'] == '1001')
    assert [l['running_balance'] for l in cash_sec['lines']] == [500.0, 300.0]
    assert cash_sec['closing_balance'] == 300.0
    assert cash_sec['total_debit'] == 500.0
    assert cash_sec['total_credit'] == 200.0


def test_hide_empty_skips_zero_no_movement_keeps_opening_only(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _acct('1002', 'Unused Bank')  # never touched -> omitted
    _entry(b.id, date(2026, 5, 1), 'JE-1', [(cash, 1000, 0), (rev, 0, 1000)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    codes = [a['code'] for a in gl['accounts']]
    assert '1002' not in codes      # zero opening + no movement -> skipped
    assert '1001' in codes          # opening-only account is kept


def test_account_id_filter_returns_single_account(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-1', [(cash, 500, 0), (rev, 0, 500)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id, account_id=cash.id)
    assert [a['code'] for a in gl['accounts']] == ['1001']


def test_branch_scope_excludes_other_branch(db_session):
    b1 = _branch('B1', 'B1')
    b2 = _branch('B2', 'B2')
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b2.id, date(2026, 6, 5), 'JE-X', [(cash, 999, 0), (rev, 0, 999)])
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b1.id)
    assert gl['accounts'] == []


def test_draft_entries_excluded(db_session):
    b = _branch()
    cash = _acct('1001', 'Cash')
    rev = _acct('4001', 'Revenue', 'Income', 'Credit')
    _entry(b.id, date(2026, 6, 5), 'JE-D', [(cash, 700, 0), (rev, 0, 700)], status='draft')
    gl = generate_general_ledger(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert gl['accounts'] == []
