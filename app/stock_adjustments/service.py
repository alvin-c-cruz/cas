"""Stock-ledger write path (R-03 slice 2a-i). post_movement is the single
primitive every future caller (RR/DR/material issue/production/returns) will
reuse; in 2a-i only the Stock Adjustment document calls it. It does NOT commit
-- the caller owns the transaction so the movement, the balance update, and the
JE all commit or roll back together.

Concurrency: the StockBalance row is updated with a conditional
UPDATE ... WHERE id=? AND row_version=? (optimistic-lock-conditional-update).
The movement's balance_*_after snapshot is computed from the balance read that
WON the race, inside the retry loop -- a retry means the prior read was stale.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.posting.control_accounts import get_control_account
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.stock_adjustments.costing import compute_new_balance
from app.stock_adjustments.models import StockMovement, StockBalance

ZERO = Decimal('0')
MAX_ATTEMPTS = 5


def _get_or_create_balance(product_id, branch_id):
    bal = StockBalance.query.filter_by(product_id=product_id, branch_id=branch_id).first()
    if bal is None:
        bal = StockBalance(product_id=product_id, branch_id=branch_id,
                           quantity_on_hand=ZERO, average_unit_cost=ZERO, total_value=ZERO)
        db.session.add(bal)
        db.session.flush()   # need bal.id; unique constraint guards a concurrent create
    return bal


def _claim_balance_update(balance_id, read_version, new_qty, new_avg, new_value):
    """Conditional UPDATE: succeeds for exactly one holder of read_version.
    Returns True on success, False if a concurrent writer already advanced it."""
    result = db.session.execute(
        db.update(StockBalance)
        .where(StockBalance.id == balance_id, StockBalance.row_version == read_version)
        .values(quantity_on_hand=new_qty, average_unit_cost=new_avg,
                total_value=new_value, row_version=StockBalance.row_version + 1,
                updated_at=ph_now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def post_movement(product, branch_id, movement_type, delta_qty, in_unit_cost,
                  source_document_type, source_document_id, reason, actor, journal_entry_id=None):
    """Apply one stock movement. Returns (StockMovement, went_negative). Does not commit."""
    delta_qty = Decimal(delta_qty)
    bal = _get_or_create_balance(product.id, branch_id)

    for _ in range(MAX_ATTEMPTS):
        read_version = bal.row_version
        old_qty = Decimal(bal.quantity_on_hand)
        old_avg = Decimal(bal.average_unit_cost)
        new_qty, new_avg = compute_new_balance(
            product.costing_method or 'moving_average', old_qty, old_avg,
            delta_qty, in_unit_cost, product.standard_cost)
        new_value = (new_qty * new_avg).quantize(Decimal('0.01'))

        if _claim_balance_update(bal.id, read_version, new_qty, new_avg, new_value):
            # the cost this movement itself is valued at:
            if delta_qty > ZERO and (product.costing_method or 'moving_average') != 'standard':
                move_unit_cost = Decimal(in_unit_cost)
            else:
                move_unit_cost = new_avg   # issues, and all standard moves, value at the (new) avg/standard
            mv = StockMovement(
                product_id=product.id, branch_id=branch_id, movement_type=movement_type,
                quantity=delta_qty.quantize(Decimal('0.0001')), unit_cost=move_unit_cost,
                balance_qty_after=new_qty, balance_avg_cost_after=new_avg, balance_value_after=new_value,
                source_document_type=source_document_type, source_document_id=source_document_id,
                journal_entry_id=journal_entry_id, reason=reason,
                created_at=ph_now(), created_by_id=actor.id)
            db.session.add(mv)
            db.session.flush()
            db.session.expire(bal, ['row_version', 'quantity_on_hand', 'average_unit_cost', 'total_value'])
            return mv, (new_qty < ZERO)

        db.session.expire(bal)   # lost the race: re-read and retry
    raise RuntimeError('stock balance update failed after retries (persistent contention)')


def reverse_document_movements(source_document_type, source_document_id, actor):
    """Post an opposite movement for each original movement of a document (void).
    Reversal is at the SAME cost basis as the original (append-only ledger)."""
    originals = StockMovement.query.filter_by(
        source_document_type=source_document_type, source_document_id=source_document_id
    ).order_by(StockMovement.id).all()
    reversals = []
    for orig in originals:
        product = orig.product
        mv, _ = post_movement(
            product, orig.branch_id, 'adjustment', -Decimal(orig.quantity),
            Decimal(orig.unit_cost), source_document_type, source_document_id,
            f'Reversal of movement {orig.id}', actor)
        reversals.append(mv)
    return reversals


def _offset_key(reason_type):
    return 'inventory_opening_equity' if reason_type == 'opening' else 'inventory_adjustment'


def _new_je(entry_number, entry_date, description, reference, branch_id, actor):
    je = JournalEntry(entry_number=entry_number, entry_date=entry_date, description=description,
                      reference=reference, entry_type='stock_adjustment', branch_id=branch_id,
                      created_by_id=actor.id, status='posted', posted_by_id=actor.id,
                      posted_at=ph_now(), is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je)
    db.session.flush()
    return je


def _add_line(je, n, account_id, description, debit, credit):
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=account_id,
                                    description=description, debit_amount=debit, credit_amount=credit))


def _line_value(line, product):
    """The money value of one adjustment line: positive line at entered cost
    (or standard for standard-cost products); negative line at the CURRENT
    balance average (read BEFORE this document's own movements are applied)."""
    method = product.costing_method or 'moving_average'
    qty = Decimal(line.quantity_delta)
    if qty > ZERO:
        if method == 'standard':
            unit = Decimal(product.standard_cost)
        else:
            unit = Decimal(line.unit_cost)
        return (qty * unit).quantize(Decimal('0.01')), unit
    # negative: value at the CURRENT balance average (read before movements applied)
    bal = StockBalance.query.filter_by(product_id=product.id, branch_id=line.adjustment.branch_id).first()
    unit = Decimal(bal.average_unit_cost) if bal else ZERO
    return (abs(qty) * unit).quantize(Decimal('0.01')), unit


def approve_adjustment(adjustment, actor):
    """Post movements + one balanced JE. Resolves control accounts BEFORE any
    write (fail-closed, zero side effects on a missing account)."""
    inv_account = get_control_account('inventory')                             # raises if unassigned
    offset_account = get_control_account(_offset_key(adjustment.reason_type))  # raises if unassigned

    je = _new_je(generate_entry_number(adjustment.branch_id), adjustment.adjustment_date,
                 f'Stock Adjustment {adjustment.sa_number}', adjustment.sa_number,
                 adjustment.branch_id, actor)
    n = 1
    warnings = []
    for line in adjustment.lines:
        product = line.product
        # value MUST be computed BEFORE post_movement for this line: a negative
        # line is valued at the balance average as it stood before this adjustment.
        value, _unit = _line_value(line, product)
        qty = Decimal(line.quantity_delta)
        in_cost = line.unit_cost if qty > ZERO else None
        mv, went_negative = post_movement(
            product, adjustment.branch_id, 'adjustment', qty, in_cost,
            'stock_adjustment', adjustment.id, line.note, actor, journal_entry_id=je.id)
        if went_negative:
            warnings.append(product.code)
        if qty > ZERO:   # stock in: Dr inventory / Cr offset
            _add_line(je, n, inv_account.id, f'{product.code} stock in', value, ZERO); n += 1
            _add_line(je, n, offset_account.id, f'{product.code} offset', ZERO, value); n += 1
        else:            # stock out: Dr offset / Cr inventory
            _add_line(je, n, offset_account.id, f'{product.code} offset', value, ZERO); n += 1
            _add_line(je, n, inv_account.id, f'{product.code} stock out', ZERO, value); n += 1

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Stock Adjustment {adjustment.sa_number} JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    adjustment.journal_entry_id = je.id
    adjustment.status = 'posted'
    adjustment.posted_by_id = actor.id
    adjustment.posted_at = ph_now()
    adjustment._negative_warnings = warnings   # transient, read by the view for a flash
    return adjustment


def void_adjustment(adjustment, actor):
    """Reverse movements + post a reversing JE, mirroring the ORIGINAL legs
    (swap Dr/Cr) -- a void reverses exactly what was booked, not a fresh
    valuation from current balances."""
    reverse_document_movements('stock_adjustment', adjustment.id, actor)
    orig = adjustment.journal_entry
    je = _new_je(generate_entry_number(adjustment.branch_id), ph_now().date(),
                 f'Void Stock Adjustment {adjustment.sa_number}', adjustment.sa_number,
                 adjustment.branch_id, actor)
    for i, line in enumerate(orig.lines, start=1):
        _add_line(je, i, line.account_id, f'Void {adjustment.sa_number}',
                  line.credit_amount, line.debit_amount)   # swap Dr/Cr
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Void Stock Adjustment {adjustment.sa_number} JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    adjustment.status = 'voided'
    return adjustment
