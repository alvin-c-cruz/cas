"""period_balances()/ledger_lines() on the GAAP basis must equal the per-account SQL the
reports ran before the seam existed: posted only, optional branch, optional date bounds,
optional closing-entry exclusion."""
from datetime import date
from decimal import Decimal
import pytest

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports import ledger as L

pytestmark = [pytest.mark.owners_basis, pytest.mark.unit]


def _acct(code, atype, normal):
    a = Account(code=code, name=f'A{code}', account_type=atype, normal_balance=normal, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _post(branch_id, debit_acct, credit_acct, amount, number, on, entry_type='adjustment', status='posted'):
    amt = Decimal(str(amount))
    je = JournalEntry(entry_number=number, entry_date=on, description='d', reference=number,
                      entry_type=entry_type, branch_id=branch_id, status=status,
                      is_balanced=True, total_debit=amt, total_credit=amt)
    db.session.add(je); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=debit_acct.id,
                                    debit_amount=amt, credit_amount=Decimal('0')))
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=2, account_id=credit_acct.id,
                                    debit_amount=Decimal('0'), credit_amount=amt))
    db.session.commit()
    return je


@pytest.fixture
def books(db_session, main_branch, branch_manila):
    cash = _acct('10101', 'Asset', 'Debit')
    sales = _acct('40001', 'Revenue', 'Credit')
    re_ = _acct('30201', 'Equity', 'Credit')
    _post(main_branch.id, cash, sales, 100, 'J1', date(2026, 1, 10))
    _post(main_branch.id, cash, sales, 50, 'J2', date(2026, 2, 5))
    _post(main_branch.id, sales, re_, 150, 'J3', date(2026, 2, 28), entry_type='closing')
    _post(main_branch.id, cash, sales, 999, 'J4', date(2026, 2, 6), status='draft')
    _post(branch_manila.id, cash, sales, 7, 'J5', date(2026, 2, 7))
    return {'cash': cash, 'sales': sales, 're': re_, 'main': main_branch.id, 'manila': branch_manila.id}


def test_balances_posted_only_branch_scoped(books):
    b = L.period_balances(None, date(2026, 12, 31), books['main'])
    assert b[books['cash'].id] == (Decimal('150.00'), Decimal('0.00'))
    assert b[books['sales'].id] == (Decimal('150.00'), Decimal('150.00'))   # closing debit included
    assert books['re'].id in b


def test_balances_exclude_closing_and_bound_by_dates(books):
    b = L.period_balances(date(2026, 2, 1), date(2026, 2, 28), books['main'], exclude_closing=True)
    assert b[books['sales'].id] == (Decimal('0.00'), Decimal('50.00'))
    assert books['re'].id not in b


def test_balances_all_branches_when_branch_none(books):
    b = L.period_balances(None, None, None)
    assert b[books['cash'].id][0] == Decimal('157.00')


def test_ledger_lines_ordered_and_filterable(books):
    lines = L.ledger_lines(date(2026, 1, 1), date(2026, 12, 31), books['main'], account_id=books['sales'].id)
    assert [l.entry_number for l in lines] == ['J1', 'J2', 'J3']
    assert lines[0].credit == Decimal('100.00') and lines[0].debit == Decimal('0.00')
    assert lines[0].moved_from_account_id is None
    assert lines[0].description == 'd'                    # falls back to entry description
    assert lines[0].display_number == 'J1'


def test_owners_not_yet_available_raises(books):
    with pytest.raises(NotImplementedError):
        L.period_balances(None, None, books['main'], reporting_basis=L.OWNERS)
