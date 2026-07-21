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


from app import db
from app.stock_adjustments.models import StockLayerConsumption, StockBalance


def fifo_apply_receive(product_id, branch_id, qty, unit_cost, source_movement, received_at):
    """Write phase -- call ONLY after the movement's balance claim has
    succeeded. Creates exactly one new layer."""
    layer = StockCostLayer(
        product_id=product_id, branch_id=branch_id,
        original_qty=Decimal(qty).quantize(QTY_Q), remaining_qty=Decimal(qty).quantize(QTY_Q),
        unit_cost=Decimal(unit_cost).quantize(MONEY_Q), received_at=received_at,
        source_movement_id=source_movement.id)
    db.session.add(layer)
    db.session.flush()
    return layer


def fifo_apply_consume(plan, movement):
    """Write phase -- call ONLY after the movement's balance claim has
    succeeded. plan is the list of (layer, qty) pairs from
    fifo_plan_consume. A layer from the plan that isn't yet in the session
    (the zero-cost deficit fallback fifo_plan_consume builds when no layer
    exists at all for this product/branch) is added here -- it carries
    received_at=None from the planning phase (fine there, since it's never
    persisted), which would violate StockCostLayer.received_at's NOT NULL
    constraint if flushed as-is; backfill it to "now" at the moment it
    actually becomes real."""
    for layer, qty in plan:
        if layer.id is None:
            if layer.received_at is None:
                layer.received_at = movement.created_at
            db.session.add(layer)
            db.session.flush()
        layer.remaining_qty = (Decimal(layer.remaining_qty) - qty).quantize(QTY_Q)
        db.session.add(StockLayerConsumption(
            movement_id=movement.id, layer_id=layer.id,
            qty_consumed=qty.quantize(QTY_Q), unit_cost_at_consumption=layer.unit_cost))
    db.session.flush()


def bootstrap_opening_layer_if_needed(product_id, branch_id):
    """If this product/branch has zero StockCostLayer rows and a nonzero
    current StockBalance, seed one opening layer from that snapshot. No-op
    otherwise. Idempotent (existence-checked) -- safe to call speculatively
    before a balance claim has even been attempted, since the fact it
    records (the CURRENT balance snapshot) doesn't depend on which specific
    movement is being posted."""
    from app.utils import ph_now
    existing = StockCostLayer.query.filter_by(product_id=product_id, branch_id=branch_id).first()
    if existing is not None:
        return
    bal = StockBalance.query.filter_by(product_id=product_id, branch_id=branch_id).first()
    if bal is None or Decimal(bal.quantity_on_hand) == ZERO:
        return
    layer = StockCostLayer(
        product_id=product_id, branch_id=branch_id,
        original_qty=bal.quantity_on_hand, remaining_qty=bal.quantity_on_hand,
        unit_cost=bal.average_unit_cost, received_at=ph_now(), source_movement_id=None)
    db.session.add(layer)
    db.session.flush()
