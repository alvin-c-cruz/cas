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
                  source_document_type, source_document_id, reason, actor, journal_entry_id=None,
                  lot_id=None, lot_reference=None):
    """Apply one stock movement. Returns (StockMovement, went_negative). Does not commit.

    FIFO branch (R-03 2b): plan-only reads happen fresh every retry attempt,
    inside the loop, before the balance claim; the corresponding layer WRITES
    (fifo_apply_receive/fifo_apply_consume) happen only after that same
    attempt's claim has already succeeded -- never before, to avoid
    double-writing layers if a losing attempt retries.

    Specific-identification branch (R-03 2d): unlike FIFO, there is no
    auto-planning -- the caller (the view layer, informed by the user's own
    lot pick) supplies lot_id up front for a negative delta_qty. Re-validated
    fresh every retry attempt (specific_id_plan_consume re-reads the lot's
    current remaining_qty), same discipline as FIFO's plan-then-apply."""
    from app.stock_adjustments.fifo import (fifo_plan_consume, fifo_apply_receive,
                                            fifo_apply_consume, bootstrap_opening_layer_if_needed)
    from app.stock_adjustments.lots import (specific_id_plan_receive, specific_id_plan_consume,
                                            specific_id_apply_receive, specific_id_apply_consume)
    delta_qty = Decimal(delta_qty)
    bal = _get_or_create_balance(product.id, branch_id)
    is_fifo = (product.costing_method == 'fifo')
    is_specific_id = (product.costing_method == 'specific_identification')
    if is_fifo:
        bootstrap_opening_layer_if_needed(product.id, branch_id)

    for _ in range(MAX_ATTEMPTS):
        read_version = bal.row_version
        old_qty = Decimal(bal.quantity_on_hand)
        old_avg = Decimal(bal.average_unit_cost)

        fifo_plan = None
        specific_lot = None
        if is_fifo:
            new_qty = (old_qty + delta_qty).quantize(Decimal('0.0001'))
            if delta_qty > ZERO:
                move_unit_cost = Decimal(in_unit_cost).quantize(Decimal('0.01'))
                new_total_value = old_qty * old_avg + delta_qty * move_unit_cost
            else:
                fifo_plan, move_unit_cost = fifo_plan_consume(product.id, branch_id, -delta_qty)
                total_cost_drawn = sum((take * Decimal(layer.unit_cost) for layer, take in fifo_plan),
                                       ZERO)
                new_total_value = old_qty * old_avg - total_cost_drawn
            new_avg = (new_total_value / new_qty).quantize(Decimal('0.01')) if new_qty != ZERO else ZERO
        elif is_specific_id:
            new_qty = (old_qty + delta_qty).quantize(Decimal('0.0001'))
            if delta_qty > ZERO:
                move_unit_cost = specific_id_plan_receive(in_unit_cost)
                new_total_value = old_qty * old_avg + delta_qty * move_unit_cost
            else:
                if lot_id is None:
                    raise ValueError('A specific-identification issue requires a lot to be selected.')
                specific_lot, move_unit_cost = specific_id_plan_consume(
                    product.id, branch_id, lot_id, -delta_qty)
                new_total_value = old_qty * old_avg - (-delta_qty) * move_unit_cost
            new_avg = (new_total_value / new_qty).quantize(Decimal('0.01')) if new_qty != ZERO else ZERO
        else:
            new_qty, new_avg = compute_new_balance(
                product.costing_method or 'moving_average', old_qty, old_avg,
                delta_qty, in_unit_cost, product.standard_cost)
            move_unit_cost = None   # resolved below, unchanged from before this task
        new_value = (new_qty * new_avg).quantize(Decimal('0.01'))

        if _claim_balance_update(bal.id, read_version, new_qty, new_avg, new_value):
            if not is_fifo and not is_specific_id:
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
            if is_fifo:
                if delta_qty > ZERO:
                    fifo_apply_receive(product.id, branch_id, delta_qty, move_unit_cost, mv, mv.created_at)
                else:
                    fifo_apply_consume(fifo_plan, mv)
            elif is_specific_id:
                if delta_qty > ZERO:
                    specific_id_apply_receive(product.id, branch_id, delta_qty, move_unit_cost,
                                              lot_reference, mv, mv.created_at)
                else:
                    specific_id_apply_consume(specific_lot, -delta_qty, mv)
            db.session.expire(bal, ['row_version', 'quantity_on_hand', 'average_unit_cost', 'total_value'])
            return mv, (new_qty < ZERO)

        db.session.expire_all()  # lost the race: re-read EVERYTHING fresh, not just bal --
                                 # a FIFO/specific-ID retry must not reuse identity-mapped
                                 # StockCostLayer/StockLot objects from the losing attempt
    raise RuntimeError('stock balance update failed after retries (persistent contention)')


class FifoLayerConsumedError(ValueError):
    """Raised when voiding a FIFO IN-movement (receipt/production/sales-return)
    whose created layer has already been drawn down by something else --
    reversal is refused rather than silently corrupting FIFO order. A
    ValueError subclass so every existing generic 'except ValueError'
    call-site pattern already catches it and flashes its message."""
    pass


def reverse_document_movements(source_document_type, source_document_id, actor, journal_entry_id=None):
    """Post an opposite movement for each original movement of a document (void).
    For a non-FIFO product: reversal is at the SAME cost basis as the original
    (append-only ledger), via the generic post_movement path -- unchanged from
    before R-03 2b. For a FIFO product: reversal is TARGETED (see
    _reverse_fifo_movement) and can raise FifoLayerConsumedError.
    journal_entry_id links each reversal movement to the JE that reversed it
    (the VOID's own new JE, not the original approval's) -- pass the id of a
    JE already created by the caller; this function does not create one."""
    originals = StockMovement.query.filter_by(
        source_document_type=source_document_type, source_document_id=source_document_id
    ).order_by(StockMovement.id).all()
    reversals = []
    for orig in originals:
        product = orig.product
        if product.costing_method == 'fifo':
            mv = _reverse_fifo_movement(orig, actor, journal_entry_id)
        elif product.costing_method == 'specific_identification':
            mv = _reverse_specific_id_movement(orig, actor, journal_entry_id)
        else:
            mv, _ = post_movement(
                product, orig.branch_id, 'adjustment', -Decimal(orig.quantity),
                Decimal(orig.unit_cost), source_document_type, source_document_id,
                f'Reversal of movement {orig.id}', actor, journal_entry_id=journal_entry_id)
        reversals.append(mv)
    return reversals


def _reverse_fifo_movement(orig, actor, journal_entry_id):
    """FIFO-aware reversal for one original movement. An OUT original (issue/
    consumption/purchase-return) restores exactly the layers its
    StockLayerConsumption rows recorded. An IN original (receipt/production/
    sales-return) targets its own source_movement_id-linked layer directly --
    never the generic oldest-first plan, which could touch the wrong layer --
    and refuses (FifoLayerConsumedError) if anything has drawn from it since.
    Mirrors post_movement's own retry/claim skeleton deliberately, not
    reusing it directly: the write conditions differ enough (targeted layer
    restore vs. generic planning) that sharing the loop body would need a
    callback layer of its own."""
    from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption
    orig_qty = Decimal(orig.quantity)
    bal = _get_or_create_balance(orig.product_id, orig.branch_id)

    for _ in range(MAX_ATTEMPTS):
        read_version = bal.row_version
        old_qty = Decimal(bal.quantity_on_hand)
        old_avg = Decimal(bal.average_unit_cost)
        reversal_qty = -orig_qty
        new_qty = (old_qty + reversal_qty).quantize(Decimal('0.0001'))

        consumptions = None
        layer = None
        if orig_qty < ZERO:
            consumptions = StockLayerConsumption.query.filter_by(movement_id=orig.id).all()
            restore_value = sum((Decimal(c.qty_consumed) * Decimal(c.unit_cost_at_consumption)
                                 for c in consumptions), ZERO)
            new_total_value = old_qty * old_avg + restore_value
        else:
            layer = StockCostLayer.query.filter_by(source_movement_id=orig.id).first()
            if layer is None:
                raise ValueError(f'No FIFO layer found for movement {orig.id} -- data integrity error.')
            if Decimal(layer.remaining_qty) != Decimal(layer.original_qty):
                consumers = StockLayerConsumption.query.filter_by(layer_id=layer.id).all()
                names = sorted({f'{c.movement.source_document_type} #{c.movement.source_document_id}'
                               for c in consumers}) or ['another transaction']
                consumed = Decimal(layer.original_qty) - Decimal(layer.remaining_qty)
                raise FifoLayerConsumedError(
                    f'Cannot reverse movement {orig.id} -- {consumed} of {layer.original_qty} units '
                    f'from its FIFO layer have already been consumed by {", ".join(names)}.')
            new_total_value = old_qty * old_avg - Decimal(layer.original_qty) * Decimal(layer.unit_cost)

        new_avg = (new_total_value / new_qty).quantize(Decimal('0.01')) if new_qty != ZERO else ZERO
        new_value = (new_qty * new_avg).quantize(Decimal('0.01'))

        if _claim_balance_update(bal.id, read_version, new_qty, new_avg, new_value):
            mv = StockMovement(
                product_id=orig.product_id, branch_id=orig.branch_id, movement_type='adjustment',
                quantity=reversal_qty.quantize(Decimal('0.0001')), unit_cost=Decimal(orig.unit_cost),
                balance_qty_after=new_qty, balance_avg_cost_after=new_avg, balance_value_after=new_value,
                source_document_type=orig.source_document_type, source_document_id=orig.source_document_id,
                journal_entry_id=journal_entry_id, reason=f'Reversal of movement {orig.id}',
                created_at=ph_now(), created_by_id=actor.id)
            db.session.add(mv)
            db.session.flush()
            if orig_qty < ZERO:
                for c in consumptions:
                    c.layer.remaining_qty = (Decimal(c.layer.remaining_qty)
                                             + Decimal(c.qty_consumed)).quantize(Decimal('0.0001'))
            else:
                layer.remaining_qty = Decimal('0.0000')
            db.session.expire(bal, ['row_version', 'quantity_on_hand', 'average_unit_cost', 'total_value'])
            return mv

        db.session.expire(bal)
    raise RuntimeError('stock balance update failed after retries (persistent contention)')


class SpecificIdLotConsumedError(ValueError):
    """Raised when voiding a specific-identification IN-movement (receipt)
    whose created lot has already been drawn down by something else --
    reversal is refused rather than silently corrupting the lot's audit
    trail. A ValueError subclass so every existing generic 'except
    ValueError' call-site pattern already catches it and flashes its
    message. Mirrors FifoLayerConsumedError exactly."""
    pass


def _reverse_specific_id_movement(orig, actor, journal_entry_id):
    """Specific-identification-aware reversal for one original movement. An
    OUT original (issue) restores exactly the ONE lot its single
    StockLotConsumption row recorded -- never more than one, since a
    specific-ID line can only ever draw from one lot (no auto-splitting).
    An IN original (receipt) targets its own source_movement_id-linked lot
    directly and refuses (SpecificIdLotConsumedError) if anything has drawn
    from it since. Mirrors _reverse_fifo_movement's retry/claim skeleton,
    simplified: a specific-ID OUT movement has AT MOST ONE consumption row
    to restore, never several."""
    from app.stock_adjustments.models import StockLot, StockLotConsumption
    orig_qty = Decimal(orig.quantity)
    bal = _get_or_create_balance(orig.product_id, orig.branch_id)

    for _ in range(MAX_ATTEMPTS):
        read_version = bal.row_version
        old_qty = Decimal(bal.quantity_on_hand)
        old_avg = Decimal(bal.average_unit_cost)
        reversal_qty = -orig_qty
        new_qty = (old_qty + reversal_qty).quantize(Decimal('0.0001'))

        consumption = None
        lot = None
        if orig_qty < ZERO:
            consumption = StockLotConsumption.query.filter_by(movement_id=orig.id).first()
            if consumption is None:
                raise ValueError(f'No lot consumption record found for movement {orig.id} -- data integrity error.')
            restore_value = Decimal(consumption.qty_consumed) * Decimal(consumption.unit_cost_at_consumption)
            new_total_value = old_qty * old_avg + restore_value
        else:
            lot = StockLot.query.filter_by(source_movement_id=orig.id).first()
            if lot is None:
                raise ValueError(f'No lot found for movement {orig.id} -- data integrity error.')
            if Decimal(lot.remaining_qty) != Decimal(lot.original_qty):
                consumers = StockLotConsumption.query.filter_by(lot_id=lot.id).all()
                names = sorted({f'{c.movement.source_document_type} #{c.movement.source_document_id}'
                               for c in consumers}) or ['another transaction']
                consumed = Decimal(lot.original_qty) - Decimal(lot.remaining_qty)
                raise SpecificIdLotConsumedError(
                    f'Cannot reverse movement {orig.id} -- {consumed} of {lot.original_qty} units '
                    f'from this lot have already been consumed by {", ".join(names)}.')
            new_total_value = old_qty * old_avg - Decimal(lot.original_qty) * Decimal(lot.unit_cost)

        new_avg = (new_total_value / new_qty).quantize(Decimal('0.01')) if new_qty != ZERO else ZERO
        new_value = (new_qty * new_avg).quantize(Decimal('0.01'))

        if _claim_balance_update(bal.id, read_version, new_qty, new_avg, new_value):
            mv = StockMovement(
                product_id=orig.product_id, branch_id=orig.branch_id, movement_type='adjustment',
                quantity=reversal_qty.quantize(Decimal('0.0001')), unit_cost=Decimal(orig.unit_cost),
                balance_qty_after=new_qty, balance_avg_cost_after=new_avg, balance_value_after=new_value,
                source_document_type=orig.source_document_type, source_document_id=orig.source_document_id,
                journal_entry_id=journal_entry_id, reason=f'Reversal of movement {orig.id}',
                created_at=ph_now(), created_by_id=actor.id)
            db.session.add(mv)
            db.session.flush()
            if orig_qty < ZERO:
                consumption.lot.remaining_qty = (Decimal(consumption.lot.remaining_qty)
                                                 + Decimal(consumption.qty_consumed)).quantize(Decimal('0.0001'))
            else:
                lot.remaining_qty = Decimal('0.0000')
            db.session.expire(bal, ['row_version', 'quantity_on_hand', 'average_unit_cost', 'total_value'])
            return mv

        db.session.expire_all()   # lost the race: re-read EVERYTHING fresh (matches post_movement's
                                  # own fix -- see feedback-plan-pattern-bug-repeats-sibling-tasks;
                                  # deliberately NOT the narrower db.session.expire(bal) 2b's own
                                  # review had to catch and fix after the fact)
    raise RuntimeError('stock balance update failed after retries (persistent contention)')


def _offset_key(reason_type):
    """Fail closed on an unrecognized reason_type, rather than defaulting to
    'inventory_adjustment' (the P&L account) -- the wrong failure direction
    for the exact safety concern this whole spec exists to address (an
    opening-stock load misrouted to income). Currently unreachable via the
    form (SelectField + DataRequired only ever submit a REASON_TYPES member),
    this is a service-layer hardening guard, not a reachable user path."""
    if reason_type == 'opening':
        return 'inventory_opening_equity'
    if reason_type == 'correction':
        return 'inventory_adjustment'
    raise ValueError(f"Unrecognized Stock Adjustment reason_type '{reason_type}' -- "
                     f"expected 'correction' or 'opening'.")


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
    balance average (read BEFORE this document's own movements are applied)
    -- except specific-identification, where a negative line is valued at
    its own PICKED LOT's cost (stable, doesn't depend on posting order)."""
    method = product.costing_method or 'moving_average'
    qty = Decimal(line.quantity_delta)
    if qty > ZERO:
        if method == 'standard':
            unit = Decimal(product.standard_cost)
        else:
            unit = Decimal(line.unit_cost)
        return (qty * unit).quantize(Decimal('0.01')), unit
    if method == 'specific_identification':
        from app.stock_adjustments.models import StockLot
        lot = db.session.get(StockLot, line.lot_id)
        if lot is None:
            raise ValueError('Stock Adjustment line references a lot that no longer exists.')
        unit = Decimal(lot.unit_cost)
        return (abs(qty) * unit).quantize(Decimal('0.01')), unit
    # negative, non-specific-id: value at the CURRENT balance average (read before movements applied)
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
            'stock_adjustment', adjustment.id, line.note, actor, journal_entry_id=je.id,
            lot_id=line.lot_id, lot_reference=line.lot_reference)
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
    """Post a reversing JE mirroring the ORIGINAL legs (swap Dr/Cr) -- a void
    reverses exactly what was booked, not a fresh valuation from current
    balances -- then reverse the stock movements, linked to THIS JE (not the
    original approval's). The JE is built first: its lines derive entirely
    from the original JE's own stored lines, independent of the movements, so
    building it before the movements loses nothing and lets the reversal
    movements carry the void's own journal_entry_id from the start."""
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
    reverse_document_movements('stock_adjustment', adjustment.id, actor, journal_entry_id=je.id)
    adjustment.status = 'voided'
    return adjustment
