# tests/integration/test_year_end_close.py
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _acct(code, name, typ, nb):
    a = Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _posted_je(branch_id, when, lines, etype='sale'):
    je = JournalEntry(entry_number=f'JE-{etype}-{when}-{lines[0][0]}', entry_date=when,
                      description='t', reference='t', entry_type=etype, branch_id=branch_id,
                      status='posted', is_balanced=True, total_debit=0, total_credit=0)
    db.session.add(je); db.session.flush()
    for i, (aid, d, c) in enumerate(lines, 1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=aid,
                                        debit_amount=Decimal(str(d)), credit_amount=Decimal(str(c))))
    db.session.flush()
    return je


def _world(branch_id):
    re = _acct('30201', 'Retained Earnings', 'Equity', 'credit')
    isum = _acct('30301', 'Current-Year Earnings', 'Equity', 'credit')
    cash = _acct('10101', 'Cash', 'Asset', 'debit')
    rev = _acct('40001', 'Service Revenue', 'Revenue', 'credit')
    exp = _acct('50201', 'Rent Expense', 'Expense', 'debit')
    # 2025 profit = 1000 revenue - 300 expense = 700
    _posted_je(branch_id, date(2025, 3, 1), [(cash.id, 1000, 0), (rev.id, 0, 1000)])
    _posted_je(branch_id, date(2025, 4, 1), [(exp.id, 300, 0), (cash.id, 0, 300)])
    return dict(re=re, isum=isum, cash=cash, rev=rev, exp=exp)


def test_close_posts_balanced_entries_and_moves_profit_to_re(db_session, admin_user, main_branch):
    from app.year_end import service
    w = _world(main_branch.id)
    db.session.commit()

    closes = service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    assert len(closes) == 1
    assert closes[0].net_income == Decimal('700.00')

    # all closing JEs balance and are tagged + dated Dec 31
    closing = JournalEntry.query.filter_by(entry_type='closing').all()
    assert len(closing) == 3
    for je in closing:
        assert je.is_balanced
        assert je.entry_date == date(2025, 12, 31)
        assert je.reference == 'CLOSE-2025'

    def net(code):
        a = Account.query.filter_by(code=code).first()
        d, c = service._posted_sums(a.id, date(2025, 12, 31), main_branch.id)
        return d - c

    # nominal accounts zeroed
    assert net('40001') == Decimal('0.00')
    assert net('50201') == Decimal('0.00')
    # income summary zeroed, RE holds the profit (credit balance => negative debit-credit)
    assert net('30301') == Decimal('0.00')
    assert net('30201') == Decimal('-700.00')


def test_close_ties_out_to_income_statement_or_raises(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.reports.financial import generate_income_statement
    _world(main_branch.id)
    db.session.commit()
    expected = Decimal(str(generate_income_statement(date(2025, 1, 1), date(2025, 12, 31),
                                                     branch_id=main_branch.id)['net_income']))
    closes = service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()
    assert closes[0].net_income == expected


def test_close_locks_periods_and_writes_audit(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.periods.models import AccountingPeriod
    _world(main_branch.id)
    db.session.commit()
    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    dec = AccountingPeriod.query.filter_by(year=2025, month=12).first()
    assert dec is not None and dec.status == 'closed'
    log = AuditLog.query.filter_by(module='year_end', action='close').first()
    assert log is not None and '2025' in (log.record_identifier or '')


def test_income_statement_excludes_closing_entries_post_close(db_session, admin_user, main_branch):
    """After closing 2025, the IS for that year must still report the real P&L (700).

    Closing entries zero out nominal accounts but are tagged entry_type='closing'.
    The IS generator must exclude them so the report reflects actual operations.
    """
    from app.year_end import service
    from app.reports.financial import generate_income_statement
    _world(main_branch.id)
    db.session.commit()

    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    result = generate_income_statement(date(2025, 1, 1), date(2025, 12, 31),
                                       branch_id=main_branch.id)
    assert result['net_income'] == 700.0, (
        f"Expected net_income=700.0 after close, got {result['net_income']}. "
        "Closing entries may not be excluded from the IS generator."
    )


def test_close_raises_if_re_account_missing(db_session, admin_user, main_branch):
    from app.year_end import service
    # nominal accounts but NO 30201/30301
    cash = _acct('10101', 'Cash', 'Asset', 'debit')
    rev = _acct('40001', 'Service Revenue', 'Revenue', 'credit')
    _posted_je(main_branch.id, date(2025, 3, 1), [(cash.id, 1000, 0), (rev.id, 0, 1000)])
    db.session.commit()
    with pytest.raises(ValueError, match='Retained Earnings'):
        service.close_fiscal_year(2025, admin_user.id)
