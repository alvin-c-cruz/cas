import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.accounts.models import Account
from app.settings import AppSettings
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory

SETTLEMENT_TYPES = ('vat_settlement', 'vat_settlement_reversal')

ZERO = Decimal('0.00')


def _q2(x):
    return Decimal(str(x)).quantize(Decimal('0.01'))


def quarter_bounds(year, quarter):
    """(first day, last day) of a calendar quarter."""
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    last = calendar.monthrange(year, end_month)[1]
    return date(year, start_month, 1), date(year, end_month, last)


def resolve_target_account(setting_key, label):
    """Resolve an accountant-assigned target account. Fail-closed: NO default code."""
    code = AppSettings.get_setting(setting_key)  # None if the accountant hasn't assigned it
    if not code:
        raise ValueError(
            f'The {label} account is not assigned. Assign the VAT Payable and Excess Input Tax '
            f'Carry-Over accounts on the VAT Settlement page before settling.')
    acct = Account.query.filter_by(code=code).first()
    if acct is None:
        raise ValueError(
            f'The assigned {label} account (code {code}) is not in the Chart of Accounts. '
            f'Re-assign it on the VAT Settlement page before settling.')
    return acct


def input_account_ids():
    rows = db.session.query(VATCategory.input_vat_account_id).filter(
        VATCategory.is_active.is_(True),
        VATCategory.input_vat_account_id.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows})


def output_account_ids():
    rows = db.session.query(SalesVATCategory.output_vat_account_id).filter(
        SalesVATCategory.is_active.is_(True),
        SalesVATCategory.output_vat_account_id.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows})


def _sum(account_ids, upto=None, start=None, end=None, exclude_settlement=False):
    """(debit_sum, credit_sum) over posted lines on account_ids with date filters."""
    if not account_ids:
        return ZERO, ZERO
    q = db.session.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntryLine.account_id.in_(account_ids),
    )
    if upto is not None:
        q = q.filter(JournalEntry.entry_date <= upto)
    if start is not None:
        q = q.filter(JournalEntry.entry_date >= start)
    if end is not None:
        q = q.filter(JournalEntry.entry_date <= end)
    if exclude_settlement:
        q = q.filter(~JournalEntry.entry_type.in_(SETTLEMENT_TYPES))
    d, c = q.one()
    return Decimal(str(d)), Decimal(str(c))


def _balance(account_ids, upto, normal, exclude_settlement=False):
    d, c = _sum(account_ids, upto=upto, exclude_settlement=exclude_settlement)
    return (d - c) if normal == 'debit' else (c - d)


def _movement(account_ids, start, end, normal):
    d, c = _sum(account_ids, start=start, end=end, exclude_settlement=True)
    return (d - c) if normal == 'debit' else (c - d)


def compute_vat_position(year, quarter):
    """Company-wide VAT position for a quarter, with the balance-vs-movement tie-out.

    Balance-based figures (as of quarter end) are what the settlement JE zeroes;
    movement-based figures (posted, non-settlement, within the quarter) are the
    independent tie-out. They agree iff every prior quarter was settled+locked and
    no VAT-category account was remapped after posting. Divergence => abort.
    """
    payable_acct = resolve_target_account('vat_payable_account_code', 'VAT Payable')
    carry_acct = resolve_target_account('input_vat_carryover_account_code',
                                        'Excess Input Tax Carry-Over')
    out_ids, in_ids = output_account_ids(), input_account_ids()
    qstart, qend = quarter_bounds(year, quarter)

    output_bal = _q2(_balance(out_ids, qend, 'credit', exclude_settlement=True))
    input_bal = _q2(_balance(in_ids, qend, 'debit', exclude_settlement=True))
    output_mv = _q2(_movement(out_ids, qstart, qend, 'credit'))
    input_mv = _q2(_movement(in_ids, qstart, qend, 'debit'))

    if output_bal != output_mv or input_bal != input_mv:
        raise ValueError(
            f'VAT settlement tie-out failed for {year} Q{quarter}: VAT-account ending '
            f'balances (output {output_bal}, input {input_bal}) do not match this '
            f"quarter's posted movement (output {output_mv}, input {input_mv}). "
            f'Settle prior quarters first, or investigate a backdated/ remapped entry.')

    prior_carryover = _q2(_balance([carry_acct.id], qstart - timedelta(days=1), 'debit'))
    creditable = _q2(input_bal + prior_carryover)
    if output_bal > creditable:
        net_payable = _q2(output_bal - creditable)
        new_carryover = ZERO
    else:
        net_payable = ZERO
        new_carryover = _q2(creditable - output_bal)

    return {
        'output_vat': output_bal, 'input_vat': input_bal,
        'prior_carryover': prior_carryover, 'creditable': creditable,
        'net_payable': net_payable, 'new_carryover': new_carryover,
        'output_ids': out_ids, 'input_ids': in_ids,
        'payable_account': payable_acct, 'carryover_account': carry_acct,
    }
