"""FIFO layer costing (R-03 slice 2b). Planning functions here are pure
reads -- they never write to the database. Apply functions (Task 3) do the
actual writes and must only be called after post_movement's balance claim
for that attempt has already succeeded (see service.py's Global Constraint
on plan-then-apply ordering)."""
from decimal import Decimal
from app.stock_adjustments.costing import QTY_Q, MONEY_Q, ZERO
from app.stock_adjustments.models import StockCostLayer


def fifo_plan_receive(unit_cost):
    """Read-only. A receive always creates exactly one new layer -- no DB
    read needed to plan it, this just normalizes the cost."""
    return Decimal(unit_cost).quantize(MONEY_Q)


def fifo_plan_consume(product_id, branch_id, qty):
    """Read-only. Returns (plan, weighted_unit_cost).

    plan is a list of (StockCostLayer, Decimal qty_from_layer) tuples,
    oldest received_at first, covering `qty`. If open layers (remaining_qty
    > 0) run out before qty is satisfied, the remainder is planned as a
    deficit against the most-recently-received layer for this product/
    branch (whatever its current remaining_qty), driving it further
    negative. If no layer exists at all yet, a transient in-memory
    StockCostLayer (never added to the session -- Task 4's caller is
    responsible for deciding whether/how to persist a deficit-only layer)
    stands in at zero cost, mirroring compute_new_balance's own existing
    zero-cost-basis fallback for a virgin negative issue under
    moving_average."""
    qty = Decimal(qty).quantize(QTY_Q)
    layers = (StockCostLayer.query
              .filter_by(product_id=product_id, branch_id=branch_id)
              .filter(StockCostLayer.remaining_qty > ZERO)
              .order_by(StockCostLayer.received_at, StockCostLayer.id)
              .all())
    plan = []
    remaining_to_consume = qty
    total_cost = ZERO
    for layer in layers:
        if remaining_to_consume <= ZERO:
            break
        take = min(Decimal(layer.remaining_qty), remaining_to_consume)
        plan.append((layer, take))
        total_cost += take * Decimal(layer.unit_cost)
        remaining_to_consume -= take

    if remaining_to_consume > ZERO:
        deficit_layer = (StockCostLayer.query
                         .filter_by(product_id=product_id, branch_id=branch_id)
                         .order_by(StockCostLayer.received_at.desc(), StockCostLayer.id.desc())
                         .first())
        if deficit_layer is None:
            deficit_layer = StockCostLayer(
                product_id=product_id, branch_id=branch_id,
                original_qty=ZERO, remaining_qty=ZERO, unit_cost=ZERO,
                received_at=None, source_movement_id=None)
        plan.append((deficit_layer, remaining_to_consume))
        total_cost += remaining_to_consume * Decimal(deficit_layer.unit_cost)

    weighted_unit_cost = (total_cost / qty).quantize(MONEY_Q) if qty > ZERO else ZERO
    return plan, weighted_unit_cost
