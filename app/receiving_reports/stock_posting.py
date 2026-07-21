# app/receiving_reports/stock_posting.py
"""Receiving Report's own GRNI accrual posting (R-03 slice 2a-ii). Wires 2a-i's
post_movement/reverse_document_movements primitives to the receipt side of the
buy-side chain.

GRNI (Goods Received Not Invoiced) is a two-step accrual: RR approval posts
Dr Inventory / Cr GRNI, net of VAT (Input VAT is recognized only at billing
time, against the real vendor invoice -- see the design doc's discussion of
BIR invoice-basis VAT timing). AP billing (app/accounts_payable/views.py)
later clears GRNI and plugs any variance -- this module owns only the
receipt side.

_new_je/_add_line are RR's own copies, mirroring the existing per-module
convention (app/petty_cash/replenishment.py and app/stock_adjustments/service.py
each have their own, not a shared abstraction) -- deliberately not extracted
into a shared helper.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.posting.control_accounts import get_control_account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.stock_adjustments.service import post_movement, reverse_document_movements

ZERO = Decimal('0.00')


def _new_je(entry_number, entry_date, description, reference, branch_id, actor):
    je = JournalEntry(entry_number=entry_number, entry_date=entry_date, description=description,
                      reference=reference, entry_type='receiving_report', branch_id=branch_id,
                      created_by_id=actor.id, status='posted', posted_by_id=actor.id,
                      posted_at=ph_now(), is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je); db.session.flush()
    return je


def _add_line(je, n, account_id, description, debit, credit):
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=account_id,
                                    description=description, debit_amount=debit, credit_amount=credit))


def _net_unit_cost(poi):
    """Extract VAT from a PO line's unit_price via its own vat_rate -- same
    net_base = amount - vat_amount math app/accounts_payable/views.py already
    uses, applied one document earlier."""
    unit_price = Decimal(str(poi.unit_price))
    vat_rate = Decimal(str(poi.vat_rate or 0))
    if vat_rate <= 0:
        return unit_price.quantize(Decimal('0.01'))
    return (unit_price / (1 + vat_rate / Decimal('100'))).quantize(Decimal('0.01'))


def post_rr_receipt(rr, actor):
    """Post a GRNI accrual for RR's tracked lines. No-op (no JE, no movements)
    if the RR has zero tracked lines. Does NOT commit."""
    tracked_lines = [li for li in rr.line_items if li.product and li.product.track_inventory]
    if not tracked_lines:
        return

    inv_account = get_control_account('inventory')
    grni_account = get_control_account('grni')

    je = _new_je(generate_entry_number(rr.branch_id), rr.receipt_date,
                 f'Receiving Report {rr.rr_number} — {rr.vendor_name}', rr.rr_number,
                 rr.branch_id, actor)
    n = 1
    for li in tracked_lines:
        poi = li.purchase_order_item
        net_unit_cost = _net_unit_cost(poi)
        net_amount = (Decimal(str(li.received_quantity)) * net_unit_cost).quantize(Decimal('0.01'))
        mv, _went_negative = post_movement(
            li.product, rr.branch_id, 'receipt', Decimal(str(li.received_quantity)), net_unit_cost,
            'receiving_report', rr.id, f'RR {rr.rr_number}', actor, journal_entry_id=je.id)
        li.stock_movement_id = mv.id
        _add_line(je, n, inv_account.id, f'{li.product.code} received', net_amount, ZERO); n += 1
        _add_line(je, n, grni_account.id, f'{li.product.code} accrued', ZERO, net_amount); n += 1

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Receiving Report {rr.rr_number} GRNI JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    rr.journal_entry_id = je.id


def reverse_rr_receipt(rr, actor):
    """Reverse a previously-posted GRNI accrual (RR cancel). No-op if the RR
    never posted one (all-untracked, or was never approved). Does NOT commit."""
    if rr.journal_entry_id is None:
        return
    orig = rr.journal_entry
    je = _new_je(generate_entry_number(rr.branch_id), ph_now().date(),
                 f'Cancel Receiving Report {rr.rr_number}', rr.rr_number, rr.branch_id, actor)
    for i, line in enumerate(orig.lines, start=1):
        _add_line(je, i, line.account_id, f'Cancel {rr.rr_number}',
                  line.credit_amount, line.debit_amount)   # swap Dr/Cr
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Cancel Receiving Report {rr.rr_number} JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    reverse_document_movements('receiving_report', rr.id, actor, journal_entry_id=je.id)
