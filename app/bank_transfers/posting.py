"""Journal-entry posting for Bank Transfers (R-04 slice 2). Four functions, one per
accounting event: intra-branch post, inter-branch initiate (sender leg), inter-branch
confirm (receiver leg), and the reject/cancel reversal (mirrors the sender leg).

JournalEntry/JournalEntryLine construction mirrors app/cash_disbursements/views.py's
_post_cdv_je / _create_cdv_reversal_je exactly: build the header with is_balanced=False
and zeroed totals, flush to get je.id, create each line with an explicit entry_id=je.id
(JournalEntry.lines is a lazy='dynamic' relationship -- appending to it before the
parent has an id/session identity is not the established pattern here), flush again,
then call je.calculate_totals() to derive total_debit/total_credit/is_balanced from the
persisted lines rather than asserting them up front.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.posting.control_accounts import get_control_account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number, generate_jv_number

ZERO = Decimal('0.00')


def _new_je(entry_number, entry_date, description, reference, entry_type, branch_id, actor,
            is_reversing=False, reversed_entry_id=None):
    je = JournalEntry(
        entry_number=entry_number,
        entry_date=entry_date,
        description=description,
        reference=reference,
        entry_type=entry_type,
        is_reversing=is_reversing,
        reversed_entry_id=reversed_entry_id,
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


def _finalize(je, transfer):
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(
            f"Bank Transfer {transfer.transfer_number} JE is not balanced "
            f"(debit={je.total_debit}, credit={je.total_credit})."
        )
    return je


def post_intra_branch_transfer(transfer, posted_by):
    """Single balanced JE, one branch: Dr to-account, Cr from-account."""
    je = _new_je(
        entry_number=generate_entry_number(transfer.from_branch_id),
        entry_date=transfer.transfer_date,
        description=f'Bank Transfer {transfer.transfer_number}',
        reference=transfer.transfer_number,
        entry_type='transfer',
        branch_id=transfer.from_branch_id,
        actor=posted_by,
    )
    memo = transfer.memo or 'Bank transfer'
    _add_line(je, 1, transfer.to_bank_account.account_id, memo, transfer.amount, ZERO)
    _add_line(je, 2, transfer.from_bank_account.account_id, memo, ZERO, transfer.amount)
    _finalize(je, transfer)

    transfer.sender_je_id = je.id
    transfer.status = 'completed'
    return je


def post_transfer_initiate(transfer, initiated_by):
    """Sender leg of an inter-branch transfer: Dr Inter-branch Due-from, Cr from-account.
    Posted in the SENDING branch's book."""
    due_from = get_control_account('inter_branch_due_from')   # raises ControlAccountError if unassigned

    je = _new_je(
        entry_number=generate_entry_number(transfer.from_branch_id),
        entry_date=transfer.transfer_date,
        description=f'Bank Transfer {transfer.transfer_number} (initiate)',
        reference=transfer.transfer_number,
        entry_type='transfer',
        branch_id=transfer.from_branch_id,
        actor=initiated_by,
    )
    memo = transfer.memo or 'Inter-branch transfer (in transit)'
    _add_line(je, 1, due_from.id, memo, transfer.amount, ZERO)
    _add_line(je, 2, transfer.from_bank_account.account_id, memo, ZERO, transfer.amount)
    _finalize(je, transfer)

    transfer.sender_je_id = je.id
    transfer.status = 'in_transit'
    transfer.initiated_by_id = initiated_by.id
    transfer.initiated_at = ph_now()
    return je


def post_transfer_confirm(transfer, confirmed_by):
    """Receiver leg of an inter-branch transfer: Dr to-account, Cr Inter-branch Due-to.
    Posted in the RECEIVING branch's book."""
    due_to = get_control_account('inter_branch_due_to')   # raises ControlAccountError if unassigned

    je = _new_je(
        entry_number=generate_entry_number(transfer.to_branch_id),
        entry_date=transfer.transfer_date,
        description=f'Bank Transfer {transfer.transfer_number} (confirm)',
        reference=transfer.transfer_number,
        entry_type='transfer',
        branch_id=transfer.to_branch_id,
        actor=confirmed_by,
    )
    memo = transfer.memo or 'Inter-branch transfer received'
    _add_line(je, 1, transfer.to_bank_account.account_id, memo, transfer.amount, ZERO)
    _add_line(je, 2, due_to.id, memo, ZERO, transfer.amount)
    _finalize(je, transfer)

    transfer.receiver_je_id = je.id
    transfer.status = 'completed'
    transfer.confirmed_by_id = confirmed_by.id
    transfer.confirmed_at = ph_now()
    return je


def post_transfer_reversal(transfer, actor, new_status):
    """Reverses the SENDER leg only (v1 reversal is in_transit-only -- the receiver
    leg was never posted at this point, per the reject/cancel gate that will live in
    the views layer). Used by both reject and cancel; they differ only by actor/branch
    check and the resulting status, enforced by the caller, not this function.

    Mirrors app/cash_disbursements/views.py's _create_cdv_reversal_je convention: a
    reversal is a General Journal entry (generate_jv_number, entry_type='reversal',
    is_reversing=True, reversed_entry_id pointing at the JE being reversed).
    """
    if new_status not in ('rejected', 'cancelled'):
        raise ValueError(f"new_status must be 'rejected' or 'cancelled', got {new_status!r}")

    due_from = get_control_account('inter_branch_due_from')

    je = _new_je(
        entry_number=generate_jv_number(transfer.from_branch_id),  # reversal is a General Journal entry
        entry_date=ph_now().date(),
        description=f'Bank Transfer {transfer.transfer_number} ({new_status})',
        reference=f'{new_status.upper()}-{transfer.transfer_number}',
        entry_type='reversal',
        branch_id=transfer.from_branch_id,
        actor=actor,
        is_reversing=True,
        reversed_entry_id=transfer.sender_je_id,
    )
    memo = f'Reversal — {new_status}'
    # Mirror image of the sender leg: Dr from-account, Cr Inter-branch Due-from.
    _add_line(je, 1, transfer.from_bank_account.account_id, memo, transfer.amount, ZERO)
    _add_line(je, 2, due_from.id, memo, ZERO, transfer.amount)
    _finalize(je, transfer)

    transfer.reversal_je_id = je.id
    transfer.status = new_status
    if new_status == 'rejected':
        transfer.rejected_by_id = actor.id
        transfer.rejected_at = ph_now()
    else:
        transfer.cancelled_by_id = actor.id
        transfer.cancelled_at = ph_now()
    return je
