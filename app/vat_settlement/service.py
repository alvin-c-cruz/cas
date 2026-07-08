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


def _balance(account_ids, upto, normal):
    d, c = _sum(account_ids, upto=upto)
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

    output_bal = _q2(_balance(out_ids, qend, 'credit'))
    input_bal = _q2(_balance(in_ids, qend, 'debit'))
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


from app.branches.models import Branch
from app.periods.models import AccountingPeriod
from app.audit.utils import log_audit
from app.utils import ph_now
from app.vat_settlement.models import VatSettlement


def primary_branch():
    b = Branch.query.filter_by(is_active=True).order_by(Branch.id).first()
    if b is None:
        raise ValueError('No active branch to post the settlement entry under.')
    return b


def settlement_entry_number(year, qtr_end_month, branch_id):
    prefix = f'JV-{year}-{qtr_end_month:02d}-'
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


def draft_vat_docs_in_quarter(year, quarter):
    from app.sales_invoices.models import SalesInvoice
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    qstart, qend = quarter_bounds(year, quarter)
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
                                  datecol >= qstart, datecol <= qend).all()
        found += [f'{label} {getattr(r, numcol.key)}' for r in rows]
    return found


def _has_posted_vat_movement_before(qstart):
    """Any posted, non-settlement VAT-account movement strictly before qstart."""
    ids = output_account_ids() + input_account_ids()
    if not ids:
        return False
    row = db.session.query(JournalEntryLine.id).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        ~JournalEntry.entry_type.in_(SETTLEMENT_TYPES),
        JournalEntry.entry_date < qstart,
        JournalEntryLine.account_id.in_(ids),
    ).first()
    return row is not None


def assert_settleable(year, quarter, today):
    qstart, qend = quarter_bounds(year, quarter)
    if qend > today:
        raise ValueError(f'{year} Q{quarter} has not ended yet; it can be settled on or '
                         f'after {qend.isoformat()}.')
    if VatSettlement.query.filter_by(fiscal_year=year, quarter=quarter,
                                     status='settled').first():
        raise ValueError(f'{year} Q{quarter} VAT is already settled.')
    # prior quarter must be settled if there is any earlier VAT activity
    prior_year, prior_q = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
    prior_settled = VatSettlement.query.filter_by(fiscal_year=prior_year, quarter=prior_q,
                                                  status='settled').first() is not None
    if not prior_settled and _has_posted_vat_movement_before(qstart):
        raise ValueError(f'Settle {prior_year} Q{prior_q} before settling {year} Q{quarter}.')
    drafts = draft_vat_docs_in_quarter(year, quarter)
    if drafts:
        preview = ', '.join(drafts[:5]) + ('…' if len(drafts) > 5 else '')
        raise ValueError(f'Cannot settle {year} Q{quarter}: post or void these draft documents '
                         f'first ({len(drafts)}): {preview}')


def eligible_quarters(today):
    earliest = db.session.query(func.min(JournalEntry.entry_date)).filter(
        JournalEntry.status == 'posted').scalar()
    if earliest is None:
        return []
    out = []
    y = earliest.year
    while date(y, 1, 1) <= today:
        for q in range(1, 5):
            try:
                assert_settleable(y, q, today)
                out.append((y, q))
            except ValueError:
                continue
        y += 1
    return out


def _new_settlement_je(branch_id, year, qtr_end, description, user_id):
    je = JournalEntry(
        entry_number=settlement_entry_number(year, qtr_end.month, branch_id),
        entry_date=qtr_end, description=description,
        reference=f'VAT-{year}Q{(qtr_end.month // 3)}',
        entry_type='vat_settlement', branch_id=branch_id,
        created_by_id=user_id, status='posted', posted_at=ph_now(),
        is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je); db.session.flush()
    return je


def _finalize(je):
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Settlement entry {je.entry_number} is not balanced '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')


def settle_quarter(year, quarter, user_id):
    assert_settleable(year, quarter, ph_now().date())
    pos = compute_vat_position(year, quarter)
    qstart, qend = quarter_bounds(year, quarter)
    branch = primary_branch()
    je_ids = []

    has_activity = (pos['output_vat'] != ZERO or pos['input_vat'] != ZERO
                    or pos['prior_carryover'] != ZERO)
    if has_activity:
        je = _new_settlement_je(branch.id, year, qend,
                                f'VAT settlement — {year} Q{quarter}', user_id)
        ln = 1
        # zero every output account (debit its credit balance)
        for aid in pos['output_ids']:
            bal = _q2(_balance([aid], qend, 'credit'))
            if bal != ZERO:
                db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln, account_id=aid,
                                                description='Clear Output VAT',
                                                debit_amount=bal, credit_amount=ZERO)); ln += 1
        # zero every input account (credit its debit balance)
        for aid in pos['input_ids']:
            bal = _q2(_balance([aid], qend, 'debit'))
            if bal != ZERO:
                db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln, account_id=aid,
                                                description='Clear Input VAT',
                                                debit_amount=ZERO, credit_amount=bal)); ln += 1
        carry_id = pos['carryover_account'].id
        if pos['net_payable'] > ZERO:
            if pos['prior_carryover'] > ZERO:  # draw prior carryover to zero
                db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln, account_id=carry_id,
                                                description='Apply prior Excess Input Tax',
                                                debit_amount=ZERO,
                                                credit_amount=pos['prior_carryover'])); ln += 1
            db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln,
                                            account_id=pos['payable_account'].id,
                                            description='VAT Payable',
                                            debit_amount=ZERO, credit_amount=pos['net_payable'])); ln += 1
        else:  # net creditable: move carryover to its new balance
            delta = _q2(pos['new_carryover'] - pos['prior_carryover'])
            if delta > ZERO:
                db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln, account_id=carry_id,
                                                description='Excess Input Tax carried forward',
                                                debit_amount=delta, credit_amount=ZERO)); ln += 1
            elif delta < ZERO:
                db.session.add(JournalEntryLine(entry_id=je.id, line_number=ln, account_id=carry_id,
                                                description='Excess Input Tax carried forward',
                                                debit_amount=ZERO, credit_amount=-delta)); ln += 1
        if ln > 1:  # at least one line was added
            db.session.flush(); _finalize(je); je_ids.append(je.id)
        else:  # dormant quarter: unchanged carryover, no current activity -> no JE
            db.session.delete(je); db.session.flush()

    s = VatSettlement(fiscal_year=year, quarter=quarter, status='settled',
                      output_vat=pos['output_vat'], input_vat=pos['input_vat'],
                      prior_carryover=pos['prior_carryover'], net_payable=pos['net_payable'],
                      new_carryover=pos['new_carryover'], settled_by_id=user_id, settled_at=ph_now())
    s.set_settlement_entry_ids(je_ids)
    db.session.add(s); db.session.flush()

    for m in (qstart.month, qstart.month + 1, qstart.month + 2):
        p = AccountingPeriod.get_or_create_period(year, m)
        if p.status != 'closed':
            p.status = 'closed'; p.closed_by_id = user_id; p.closed_at = ph_now()

    log_audit(module='vat_settlement', action='settle', record_id=s.id,
              record_identifier=f'{year} Q{quarter}',
              new_values={'net_payable': str(pos['net_payable']),
                          'new_carryover': str(pos['new_carryover']),
                          'settlement_entry_ids': je_ids}, user_id=user_id)
    return s


def _latest_settled():
    return VatSettlement.query.filter_by(status='settled').order_by(
        VatSettlement.fiscal_year.desc(), VatSettlement.quarter.desc()).first()


def _reverse_je(source_je, year, qtr_end, user_id):
    rev = JournalEntry(
        entry_number=settlement_entry_number(year, qtr_end.month, source_je.branch_id),
        entry_date=qtr_end, description=f'Reverse {source_je.description}',
        reference=f'VATREV-{year}Q{(qtr_end.month // 3)}',
        entry_type='vat_settlement_reversal', is_reversing=True,
        reversed_entry_id=source_je.id, branch_id=source_je.branch_id,
        posted_by_id=user_id, status='posted', posted_at=ph_now(),
        is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(rev); db.session.flush()
    for i, src in enumerate(source_je.lines.all(), start=1):
        db.session.add(JournalEntryLine(entry_id=rev.id, line_number=i, account_id=src.account_id,
                                        description=f'Reverse: {src.description or ""}',
                                        debit_amount=src.credit_amount,
                                        credit_amount=src.debit_amount))
    db.session.flush(); _finalize(rev)
    return rev


def reverse_settlement(year, quarter, user_id):
    s = VatSettlement.query.filter_by(fiscal_year=year, quarter=quarter,
                                      status='settled').first()
    if s is None:
        raise ValueError(f'{year} Q{quarter} is not settled.')
    latest = _latest_settled()
    if latest and (latest.fiscal_year, latest.quarter) != (year, quarter):
        raise ValueError(f'Only the latest settled quarter '
                         f'({latest.fiscal_year} Q{latest.quarter}) can be reversed.')
    qstart, qend = quarter_bounds(year, quarter)
    for je_id in s.get_settlement_entry_ids():
        src = db.session.get(JournalEntry, je_id)
        if src is not None:
            _reverse_je(src, year, qend, user_id)
    for m in (qstart.month, qstart.month + 1, qstart.month + 2):
        p = AccountingPeriod.query.filter_by(year=year, month=m).first()
        if p is not None and p.status == 'closed':
            p.status = 'open'; p.closed_by_id = None; p.closed_at = None
    s.status = 'reversed'; s.reversed_at = ph_now(); s.reversed_by_id = user_id
    db.session.flush()
    log_audit(module='vat_settlement', action='reverse', record_id=s.id,
              record_identifier=f'{year} Q{quarter}',
              new_values={'fiscal_year': year, 'quarter': quarter}, user_id=user_id)
    return s
