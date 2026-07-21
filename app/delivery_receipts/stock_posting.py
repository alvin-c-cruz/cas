# app/delivery_receipts/stock_posting.py
"""Delivery Receipt's own COGS-relief posting (R-03 slice 2a-iii). Wires 2a-i's
post_movement/reverse_document_movements primitives to the sell-side physical-
movement point, mirroring app/receiving_reports/stock_posting.py's shape exactly.

No VAT, no variance: COGS is a pure cost figure valued at whatever the product's
current moving-average/standard cost already is (post_movement/compute_new_balance
ignore in_unit_cost entirely for an OUT movement -- the average is unchanged by an
issue). Unlike GRNI there is nothing to reconcile against downstream (SI billing
never touches this), so this module needs no per-line model change and no
control-account beyond `cogs` itself.

_new_je/_add_line are this module's own copies, per the established per-module
convention (app/petty_cash/replenishment.py, app/stock_adjustments/service.py, and
app/receiving_reports/stock_posting.py each maintain their own -- not shared).
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
                      reference=reference, entry_type='delivery_receipt', branch_id=branch_id,
                      created_by_id=actor.id, status='posted', posted_by_id=actor.id,
                      posted_at=ph_now(), is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je); db.session.flush()
    return je


def _add_line(je, n, account_id, description, debit, credit):
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=account_id,
                                    description=description, debit_amount=debit, credit_amount=credit))


def post_dr_delivery(dr, actor):
    """Post a COGS-relief JE for dr's tracked lines. No-op (no JE, no movements)
    if the DR has zero tracked lines. Does NOT commit."""
    tracked_lines = [li for li in dr.line_items if li.product and li.product.track_inventory]
    if not tracked_lines:
        return

    cogs_account = get_control_account('cogs')
    inv_account = get_control_account('inventory')

    je = _new_je(generate_entry_number(dr.branch_id), dr.delivery_date,
                 f'Delivery Receipt {dr.dr_number} — {dr.customer_name}', dr.dr_number,
                 dr.branch_id, actor)
    n = 1
    for li in tracked_lines:
        mv, _went_negative = post_movement(
            li.product, dr.branch_id, 'issue', -Decimal(str(li.delivered_quantity)), None,
            'delivery_receipt', dr.id, f'DR {dr.dr_number}', actor, journal_entry_id=je.id)
        amount = (abs(Decimal(str(mv.quantity))) * Decimal(str(mv.unit_cost))).quantize(Decimal('0.01'))
        _add_line(je, n, cogs_account.id, f'{li.product.code} COGS', amount, ZERO); n += 1
        _add_line(je, n, inv_account.id, f'{li.product.code} relief', ZERO, amount); n += 1

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Delivery Receipt {dr.dr_number} COGS JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    dr.journal_entry_id = je.id


def reverse_dr_delivery(dr, actor):
    """Reverse a previously-posted COGS-relief JE (DR cancel). No-op if the DR
    never posted one. Does NOT commit."""
    if dr.journal_entry_id is None:
        return
    orig = dr.journal_entry
    je = _new_je(generate_entry_number(dr.branch_id), ph_now().date(),
                 f'Cancel Delivery Receipt {dr.dr_number}', dr.dr_number, dr.branch_id, actor)
    for i, line in enumerate(orig.lines, start=1):
        _add_line(je, i, line.account_id, f'Cancel {dr.dr_number}',
                  line.credit_amount, line.debit_amount)   # swap Dr/Cr
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Cancel Delivery Receipt {dr.dr_number} JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    reverse_document_movements('delivery_receipt', dr.id, actor, journal_entry_id=je.id)
