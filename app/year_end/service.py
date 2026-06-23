from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.accounts.account_types import BASE_CATEGORY, IS_TYPES
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
        if a.account_type not in IS_TYPES:
            continue
        d, c = _posted_sums(a.id, year_end, branch_id)
        if BASE_CATEGORY.get(a.account_type) == 'Revenue':
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


from app.branches.models import Branch
from app.periods.models import AccountingPeriod
from app.audit.utils import log_audit
from app.utils import ph_now
from app.reports.financial import generate_income_statement


def _require_account(code, label):
    a = Account.query.filter_by(code=code).first()
    if a is None:
        raise ValueError(f'{label} ({code}) not found in the Chart of Accounts. '
                         'Add it before closing the year.')
    return a


def _new_closing_je(branch_id, year, description, user_id=None):
    je = JournalEntry(
        entry_number=closing_entry_number(branch_id, year),
        entry_date=date(year, 12, 31),
        description=description,
        reference=f'CLOSE-{year}',
        entry_type='closing',
        branch_id=branch_id,
        created_by_id=user_id,
        status='posted',
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(je)
    db.session.flush()
    return je


def _finalize(je):
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Closing entry {je.entry_number} is not balanced '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')


def _close_branch(year, branch_id, user_id):
    re_acct = _require_account(RETAINED_EARNINGS_CODE, 'Retained Earnings')
    isum = _require_account(INCOME_SUMMARY_CODE, 'Current-Year Earnings (Income Summary)')
    bal = nominal_balances(year, branch_id)
    total_rev = sum((amt for _, amt in bal['revenue']), Decimal('0.00'))
    total_exp = sum((amt for _, amt in bal['expense']), Decimal('0.00'))
    net_income = total_rev - total_exp

    # tie-out: must equal the reported net income
    reported = Decimal(str(generate_income_statement(
        date(year, 1, 1), date(year, 12, 31), branch_id=branch_id)['net_income']))
    if net_income != reported:
        raise ValueError(f'Closing net income ({net_income}) does not reconcile with the '
                         f'Income Statement ({reported}) for {year}. Close aborted.')

    je_ids = []

    # JE1 — close revenue into income summary
    if bal['revenue']:
        je1 = _new_closing_je(branch_id, year, f'Close revenue to Income Summary — FY{year}', user_id=user_id)
        ln = 1
        for acct, amt in bal['revenue']:
            db.session.add(JournalEntryLine(entry_id=je1.id, line_number=ln, account_id=acct.id,
                                            description=f'Close {acct.code}',
                                            debit_amount=amt, credit_amount=Decimal('0.00')))
            ln += 1
        db.session.add(JournalEntryLine(entry_id=je1.id, line_number=ln, account_id=isum.id,
                                        description='Revenue to Income Summary',
                                        debit_amount=Decimal('0.00'), credit_amount=total_rev))
        db.session.flush(); _finalize(je1); je_ids.append(je1.id)

    # JE2 — close expenses into income summary
    if bal['expense']:
        je2 = _new_closing_je(branch_id, year, f'Close expenses to Income Summary — FY{year}', user_id=user_id)
        ln = 1
        db.session.add(JournalEntryLine(entry_id=je2.id, line_number=ln, account_id=isum.id,
                                        description='Expenses to Income Summary',
                                        debit_amount=total_exp, credit_amount=Decimal('0.00')))
        ln += 1
        for acct, amt in bal['expense']:
            db.session.add(JournalEntryLine(entry_id=je2.id, line_number=ln, account_id=acct.id,
                                            description=f'Close {acct.code}',
                                            debit_amount=Decimal('0.00'), credit_amount=amt))
            ln += 1
        db.session.flush(); _finalize(je2); je_ids.append(je2.id)

    # JE3 — close income summary to retained earnings
    if net_income != 0:
        je3 = _new_closing_je(branch_id, year, f'Close Income Summary to Retained Earnings — FY{year}', user_id=user_id)
        if net_income > 0:
            db.session.add(JournalEntryLine(entry_id=je3.id, line_number=1, account_id=isum.id,
                                            description='Income Summary to RE',
                                            debit_amount=net_income, credit_amount=Decimal('0.00')))
            db.session.add(JournalEntryLine(entry_id=je3.id, line_number=2, account_id=re_acct.id,
                                            description='Net income to Retained Earnings',
                                            debit_amount=Decimal('0.00'), credit_amount=net_income))
        else:
            loss = -net_income
            db.session.add(JournalEntryLine(entry_id=je3.id, line_number=1, account_id=re_acct.id,
                                            description='Net loss from Retained Earnings',
                                            debit_amount=loss, credit_amount=Decimal('0.00')))
            db.session.add(JournalEntryLine(entry_id=je3.id, line_number=2, account_id=isum.id,
                                            description='Income Summary to RE',
                                            debit_amount=Decimal('0.00'), credit_amount=loss))
        db.session.flush(); _finalize(je3); je_ids.append(je3.id)

    fc = FiscalYearClose(fiscal_year=year, branch_id=branch_id, status='closed',
                         net_income=net_income, closed_by_id=user_id,
                         closed_at=ph_now())
    fc.set_closing_entry_ids(je_ids)
    db.session.add(fc)
    db.session.flush()

    # lock the year's periods
    for month in range(1, 13):
        p = AccountingPeriod.get_or_create_period(year, month)
        if p.status != 'closed':
            p.status = 'closed'
            p.closed_by_id = user_id
            p.closed_at = ph_now()

    log_audit(module='year_end', action='close', record_id=fc.id,
              record_identifier=f'{year} / {fc.branch.name if fc.branch else branch_id}',
              new_values={'fiscal_year': year, 'branch_id': branch_id,
                          'net_income': str(net_income), 'closing_entry_ids': je_ids},
              user_id=user_id)
    return fc


def _earliest_data_year(branch_id=None):
    q = db.session.query(func.min(JournalEntry.entry_date)).filter(JournalEntry.status == 'posted')
    if branch_id:
        q = q.filter(JournalEntry.branch_id == branch_id)
    earliest = q.scalar()
    return earliest.year if earliest else None


def _has_posted_data(year):
    return db.session.query(JournalEntry.id).filter(
        JournalEntry.status == 'posted',
        func.strftime('%Y', JournalEntry.entry_date) == str(year),
    ).first() is not None


def drafts_in_year(year):
    """Labels of any draft documents dated within `year` (across the 5 document types)."""
    from app.sales_invoices.models import SalesInvoice
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    y = str(year)
    found = []
    checks = [
        (SalesInvoice, SalesInvoice.invoice_date, SalesInvoice.invoice_number, 'Sales Invoice'),
        (AccountsPayable, AccountsPayable.ap_date, AccountsPayable.ap_number, 'AP Bill'),
        (CashDisbursementVoucher, CashDisbursementVoucher.cdv_date,
         CashDisbursementVoucher.cdv_number, 'Cash Disbursement'),
        (CashReceiptVoucher, CashReceiptVoucher.crv_date,
         CashReceiptVoucher.crv_number, 'Cash Receipt'),
    ]
    for model, datecol, numcol, label in checks:
        rows = model.query.filter(model.status == 'draft',
                                  func.strftime('%Y', datecol) == y).all()
        found += [f'{label} {getattr(r, numcol.key)}' for r in rows]
    # Journal Vouchers (JournalEntry with status='draft')
    draft_jes = JournalEntry.query.filter(
        JournalEntry.status == 'draft',
        func.strftime('%Y', JournalEntry.entry_date) == y,
    ).all()
    found += [f'Journal Voucher {je.display_number}' for je in draft_jes]
    return found


def assert_closeable(year, today):
    if date(year, 12, 31) > today:
        raise ValueError(f'Fiscal year {year} has not ended yet; it can be closed on or '
                         f'after Dec 31, {year}.')
    for b in Branch.query.filter_by(is_active=True).all():
        if FiscalYearClose.query.filter_by(fiscal_year=year, branch_id=b.id,
                                            status='closed').first():
            raise ValueError(f'Fiscal year {year} is already closed.')
    earliest = _earliest_data_year()
    if earliest is not None and year > earliest:
        prior = year - 1
        prior_has_data = _has_posted_data(prior)
        prior_closed = FiscalYearClose.query.filter_by(fiscal_year=prior,
                                                       status='closed').first() is not None
        if prior_has_data and not prior_closed:
            raise ValueError(f'Close fiscal year {prior} before closing {year}.')
    drafts = drafts_in_year(year)
    if drafts:
        preview = ', '.join(drafts[:5]) + ('…' if len(drafts) > 5 else '')
        raise ValueError(f'Cannot close {year}: post or void these draft documents first '
                         f'({len(drafts)}): {preview}')


def eligible_years(today):
    earliest = _earliest_data_year()
    if earliest is None:
        return []
    years = []
    for y in range(earliest, today.year + 1):
        try:
            assert_closeable(y, today)
            years.append(y)
        except ValueError:
            continue
    return years


def close_fiscal_year(year, user_id):
    """Close `year` for every active branch.

    NOTE: not strictly all-or-nothing across branches — AccountingPeriod.get_or_create_period
    and log_audit commit internally, so with multiple active branches an earlier branch's
    close is already committed before a later branch is attempted. The per-branch tie-out
    guard runs before any posting, so the common failure modes abort that branch cleanly.
    (Single active branch today; revisit a validate-all-branches-first pass when multi-branch
    goes live.)
    """
    assert_closeable(year, ph_now().date())
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.id).all()
    return [_close_branch(year, b.id, user_id) for b in branches]


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

def _reverse_je(source_je, year, branch_id, user_id):
    rev = JournalEntry(
        entry_number=closing_entry_number(branch_id, year),
        entry_date=date(year, 12, 31),
        description=f'Reverse {source_je.description}',
        reference=f'REOPEN-{year}',
        entry_type='closing_reversal',
        is_reversing=True,
        reversed_entry_id=source_je.id,
        branch_id=branch_id,
        status='posted',
        posted_by_id=user_id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=Decimal('0.00'),
        total_credit=Decimal('0.00'),
    )
    db.session.add(rev)
    db.session.flush()
    for i, src in enumerate(source_je.lines.all(), start=1):
        db.session.add(JournalEntryLine(entry_id=rev.id, line_number=i, account_id=src.account_id,
                                        description=f'Reverse: {src.description or ""}',
                                        debit_amount=src.credit_amount,
                                        credit_amount=src.debit_amount))
    db.session.flush()
    _finalize(rev)
    return rev


def _reopen_branch(year, branch_id, user_id):
    fc = FiscalYearClose.query.filter_by(fiscal_year=year, branch_id=branch_id,
                                         status='closed').first()
    if fc is None:
        return None
    for je_id in fc.get_closing_entry_ids():
        src = db.session.get(JournalEntry, je_id)
        if src is not None:
            _reverse_je(src, year, branch_id, user_id)

    for month in range(1, 13):
        p = AccountingPeriod.query.filter_by(year=year, month=month).first()
        if p is not None and p.status == 'closed':
            p.status = 'open'
            p.closed_by_id = None
            p.closed_at = None

    fc.status = 'reopened'
    fc.reopened_at = ph_now()
    fc.reopened_by_id = user_id
    db.session.flush()
    log_audit(module='year_end', action='reopen', record_id=fc.id,
              record_identifier=f'{year} / {fc.branch.name if fc.branch else branch_id}',
              new_values={'fiscal_year': year, 'branch_id': branch_id},
              user_id=user_id)
    return fc


def reopen_fiscal_year(year, user_id):
    """Reopen `year` for every branch. Only the latest closed year may be reopened."""
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.id).all()
    for b in branches:
        latest = latest_closed_year(b.id)
        if latest is not None and year != latest:
            raise ValueError(f'Only the latest closed year ({latest}) can be reopened.')
    return [r for r in (_reopen_branch(year, b.id, user_id) for b in branches) if r]
