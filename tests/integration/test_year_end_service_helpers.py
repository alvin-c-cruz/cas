import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


def _acct(code, name, typ, nb):
    a = Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _posted_je(branch_id, when, lines):
    """lines = [(account_id, debit, credit)]."""
    je = JournalEntry(entry_number=f'JE-T-{when.isoformat()}', entry_date=when,
                      description='t', reference='t', entry_type='sale',
                      branch_id=branch_id, status='posted',
                      is_balanced=True, total_debit=0, total_credit=0)
    db.session.add(je); db.session.flush()
    for i, (aid, d, c) in enumerate(lines, 1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=aid,
                                        debit_amount=Decimal(str(d)), credit_amount=Decimal(str(c))))
    db.session.flush()
    return je


def test_nominal_balances_splits_revenue_and_expense(db_session, main_branch):
    from app.year_end import service
    rev = _acct('40001', 'Service Revenue', 'Revenue', 'credit')
    exp = _acct('50201', 'Rent Expense', 'Expense', 'debit')
    # a sale: Dr cash 1000 / Cr revenue 1000 ; an expense: Dr rent 300 / Cr cash 300
    cash = _acct('10101', 'Cash', 'Asset', 'debit')
    _posted_je(main_branch.id, date(2025, 3, 1), [(cash.id, 1000, 0), (rev.id, 0, 1000)])
    _posted_je(main_branch.id, date(2025, 4, 1), [(exp.id, 300, 0), (cash.id, 0, 300)])

    bal = service.nominal_balances(2025, main_branch.id)
    rev_map = {a.code: amt for a, amt in bal['revenue']}
    exp_map = {a.code: amt for a, amt in bal['expense']}
    assert rev_map['40001'] == Decimal('1000.00')   # credit balance
    assert exp_map['50201'] == Decimal('300.00')     # debit balance
    assert '10101' not in rev_map and '10101' not in exp_map  # cash is not nominal


def test_latest_closed_year_none_then_value(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.year_end.models import FiscalYearClose
    assert service.latest_closed_year(main_branch.id) is None
    db.session.add(FiscalYearClose(fiscal_year=2024, branch_id=main_branch.id,
                                   status='closed', net_income=Decimal('0'),
                                   closed_by_id=admin_user.id))
    db.session.commit()
    assert service.latest_closed_year(main_branch.id) == 2024
    assert service.latest_closed_year_end(main_branch.id) == date(2024, 12, 31)


def test_latest_closed_year_ignores_reopened(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.year_end.models import FiscalYearClose
    db.session.add(FiscalYearClose(fiscal_year=2024, branch_id=main_branch.id,
                                   status='reopened', net_income=Decimal('0'),
                                   closed_by_id=admin_user.id))
    db.session.commit()
    assert service.latest_closed_year(main_branch.id) is None
