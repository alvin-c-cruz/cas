"""Specific-identification lot costing (R-03 slice 2d). Planning functions
here are pure reads -- they never write to the database. Apply functions
do the actual writes and must only be called after post_movement's balance
claim for that attempt has already succeeded (mirrors fifo.py's plan-then-
apply discipline). Unlike FIFO, consumption is never auto-planned: the
caller (post_movement, told by the user's own lot pick) supplies the exact
lot_id up front -- there is no oldest/newest selection logic here at all."""
from decimal import Decimal
from app import db
from app.stock_adjustments.costing import QTY_Q, MONEY_Q
from app.stock_adjustments.models import StockLot, StockLotConsumption


def specific_id_plan_receive(unit_cost):
    """Read-only. A receive always creates exactly one new lot -- no DB
    read needed to plan it, this just normalizes the cost."""
    return Decimal(unit_cost).quantize(MONEY_Q)


def specific_id_plan_consume(product_id, branch_id, lot_id, qty):
    """Read-only. Validates the user-picked lot belongs to this product/
    branch and has enough remaining quantity for this exact draw -- no
    auto-selection, no splitting across lots (a specific-ID line always
    draws from exactly one lot the user chose). Raises ValueError (not a
    silent fallback) if the lot doesn't exist, belongs to a different
    product/branch, or doesn't have enough remaining quantity: a physical
    lot cannot go negative the way a FIFO/LIFO pooled layer's deficit
    fallback can. Returns (lot, unit_cost)."""
    qty = Decimal(qty).quantize(QTY_Q)
    lot = db.session.get(StockLot, lot_id)
    if lot is None or lot.product_id != product_id or lot.branch_id != branch_id:
        raise ValueError(f'Lot {lot_id} does not exist for this product/branch.')
    if Decimal(lot.remaining_qty) < qty:
        raise ValueError(
            f'Lot {lot.lot_reference or lot.received_at} only has {lot.remaining_qty} '
            f'units remaining; cannot issue {qty}.')
    return lot, Decimal(lot.unit_cost).quantize(MONEY_Q)


def specific_id_apply_receive(product_id, branch_id, qty, unit_cost, lot_reference,
                              source_movement, received_at):
    """Write phase -- call ONLY after the movement's balance claim has
    succeeded. Creates exactly one new lot."""
    lot = StockLot(
        product_id=product_id, branch_id=branch_id,
        original_qty=Decimal(qty).quantize(QTY_Q), remaining_qty=Decimal(qty).quantize(QTY_Q),
        unit_cost=Decimal(unit_cost).quantize(MONEY_Q), received_at=received_at,
        lot_reference=(lot_reference or None), source_movement_id=source_movement.id)
    db.session.add(lot)
    db.session.flush()
    return lot


def specific_id_apply_consume(lot, qty, movement):
    """Write phase -- call ONLY after the movement's balance claim has
    succeeded. Decrements the picked lot's remaining_qty by exactly qty and
    records ONE StockLotConsumption row -- always exactly one, never
    several, since a specific-ID line can only ever draw from one lot."""
    qty = Decimal(qty).quantize(QTY_Q)
    lot.remaining_qty = (Decimal(lot.remaining_qty) - qty).quantize(QTY_Q)
    db.session.add(StockLotConsumption(
        movement_id=movement.id, lot_id=lot.id,
        qty_consumed=qty, unit_cost_at_consumption=lot.unit_cost))
    db.session.flush()
