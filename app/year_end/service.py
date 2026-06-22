from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.reports.financial import _pl_role
from app.year_end.models import FiscalYearClose

RETAINED_EARNINGS_CODE = '30201'
INCOME_SUMMARY_CODE = '30301'
CLOSING_TYPES = ('closing', 'closing_reversal')


def _posted_sums(account_id, year_end, branch_id):
    """(debit_sum, credit_sum) of posted lines for an account, entry_date <= year_end, branch."""
    d, c = db.session.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntry.entry_date <= year_end,
        JournalEntry.branch_id == branch_id,
        JournalEntryLine.account_id == account_id,
    ).one()
    return Decimal(str(d)), Decimal(str(c))


def nominal_balances(year, branch_id):
    """Revenue (credit) and expense (debit) balances for nominal accounts as of Dec 31 `year`."""
    year_end = date(year, 12, 31)
    out = {'revenue': [], 'expense': []}
    for a in Account.query.order_by(Account.code).all():
        role = _pl_role(a)
        if role is None:
            continue
        d, c = _posted_sums(a.id, year_end, branch_id)
        if role == 'revenue':
            bal = c - d
            if bal != 0:
                out['revenue'].append((a, bal))
        else:
            bal = d - c
            if bal != 0:
                out['expense'].append((a, bal))
    return out


def closing_entry_number(branch_id, year):
    """Next JV number keyed to the close date (Dec of `year`), per branch: JV-{year}-12-NNNN."""
    prefix = f'JV-{year}-12-'
    latest = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%'),
        JournalEntry.branch_id == branch_id,
    ).order_by(JournalEntry.entry_number.desc()).first()
    nxt = 1
    if latest:
        try:
            nxt = int(latest.entry_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            nxt = 1
    return f'{prefix}{nxt:04d}'


def latest_closed_year(branch_id):
    row = (FiscalYearClose.query
           .filter_by(branch_id=branch_id, status='closed')
           .order_by(FiscalYearClose.fiscal_year.desc()).first())
    return row.fiscal_year if row else None


def latest_closed_year_end(branch_id):
    y = latest_closed_year(branch_id)
    return date(y, 12, 31) if y else None
