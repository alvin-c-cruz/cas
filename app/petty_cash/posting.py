"""Petty Cash establish/adjust/close funding JEs + no-JE voucher recording
(R-04 slice 4). The replenishment JE (the one event with a short/over plug) is
in app/petty_cash/replenishment.py, built in Task 4.

JournalEntry/JournalEntryLine construction mirrors app/bank_transfers/posting.py's
_new_je/_add_line/_finalize pattern exactly (itself mirroring
app/cash_disbursements/views.py's _post_cdv_je): build the header with
is_balanced=False and zeroed totals, flush to get je.id, add lines with an
explicit entry_id=je.id, flush again, then call je.calculate_totals() to derive
total_debit/total_credit/is_balanced from the persisted lines rather than
asserting them up front. entry_type='adjustment' is already a registered
VOUCHER_ENTRY_TYPES/VOUCHER_TYPES value (General Journal / Books of Accounts),
so no report-registration follow-up is needed here (unlike Slice 2 Task 3's
'transfer' entry_type, which needed a review-caught fix).
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.petty_cash.numbering import generate_pcv_number

ZERO = Decimal('0.00')


def _new_je(entry_number, entry_date, description, reference, branch_id, actor):
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=entry_date,
        description=description,
        reference=reference,
        entry_type='adjustment',
        branch_id=branch_id,
        created_by_id=actor.id,
        status='posted',
        posted_by_id=actor.id,
        posted_at=ph_now(),
        is_balanced=False,
        total_debit=ZERO,
        total_credit=ZERO,
    )
    db.session.add(je)
    db.session.flush()
    return je


def _add_line(je, line_number, account_id, description, debit, credit):
    line = JournalEntryLine(
        entry_id=je.id, line_number=line_number, account_id=account_id,
        description=description, debit_amount=debit, credit_amount=credit,
    )
    db.session.add(line)
    return line


def _finalize(je, fund):
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"Petty Cash Fund {fund.code} JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit})."
        )
    return je


def _funding_bank_account_id(fund):
    if fund.funding_bank_account is None:
        raise ValueError('Set a funding bank account before this action.')
    return fund.funding_bank_account.account_id


def post_establish(fund, actor):
    """Dr Petty Cash Fund / Cr Bank, for the float amount."""
    bank_account_id = _funding_bank_account_id(fund)
    je = _new_je(
        entry_number=generate_entry_number(fund.branch_id),
        entry_date=ph_now().date(),
        description=f'Establish Petty Cash Fund {fund.code}',
        reference=fund.code,
        branch_id=fund.branch_id,
        actor=actor,
    )
    _add_line(je, 1, fund.account_id, 'Establish float', fund.float_amount, ZERO)
    _add_line(je, 2, bank_account_id, 'Establish float', ZERO, fund.float_amount)
    _finalize(je, fund)
    return je


def post_adjust_float(fund, delta, actor):
    """A positive delta increases the float (Dr Petty Cash / Cr Bank); negative
    decreases it (Dr Bank / Cr Petty Cash). Updates fund.float_amount."""
    bank_account_id = _funding_bank_account_id(fund)
    amount = abs(Decimal(delta))
    increasing = delta > 0
    je = _new_je(
        entry_number=generate_entry_number(fund.branch_id),
        entry_date=ph_now().date(),
        description=f'Adjust float — {fund.code}',
        reference=fund.code,
        branch_id=fund.branch_id,
        actor=actor,
    )
    petty_debit = amount if increasing else ZERO
    petty_credit = ZERO if increasing else amount
    bank_debit = ZERO if increasing else amount
    bank_credit = amount if increasing else ZERO
    _add_line(je, 1, fund.account_id, 'Float adjustment', petty_debit, petty_credit)
    _add_line(je, 2, bank_account_id, 'Float adjustment', bank_debit, bank_credit)
    _finalize(je, fund)
    fund.float_amount = fund.float_amount + delta
    return je


def post_close(fund, actor):
    """Refuses while any held voucher exists. Dr Bank / Cr Petty Cash, zeroing
    the float back out."""
    from app.petty_cash.models import PettyCashVoucher
    held_count = PettyCashVoucher.query.filter_by(fund_id=fund.id, status='held').count()
    if held_count > 0:
        raise ValueError(f'Cannot close: {held_count} held voucher(s) must be replenished first.')
    bank_account_id = _funding_bank_account_id(fund)
    amount = fund.float_amount
    je = _new_je(
        entry_number=generate_entry_number(fund.branch_id),
        entry_date=ph_now().date(),
        description=f'Close Petty Cash Fund {fund.code}',
        reference=fund.code,
        branch_id=fund.branch_id,
        actor=actor,
    )
    _add_line(je, 1, bank_account_id, 'Close fund', amount, ZERO)
    _add_line(je, 2, fund.account_id, 'Close fund', ZERO, amount)
    _finalize(je, fund)
    fund.status = 'closed'
    return je


def record_voucher(fund, payee, expense_account_id, amount, description, receipt_ref, created_by):
    """Zero JE effect -- a held record only."""
    from app.petty_cash.models import PettyCashVoucher
    v = PettyCashVoucher(fund_id=fund.id, voucher_number=generate_pcv_number(),
                         voucher_date=ph_now().date(), payee=payee,
                         expense_account_id=expense_account_id, amount=amount,
                         description=description, receipt_ref=receipt_ref,
                         created_by_id=created_by.id, status='held')
    db.session.add(v)
    return v
