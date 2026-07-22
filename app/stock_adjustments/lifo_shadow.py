"""LIFO shadow valuation (R-03 slice 2c). Read-only, internal-reporting-only
-- LIFO is disallowed under IAS 2/PFRS for CAS's statutory/BIR-facing
figures, so this never becomes a product's real costing_method the way FIFO
(2b) did. Every function here only READS StockMovement; nothing here writes
to the database, touches post_movement/StockBalance, or affects any GL
posting. A product's real postings keep using its actual costing_method
(moving_average fallback for costing_method='lifo', unchanged since 2a-i)."""
from collections import namedtuple
from datetime import datetime, time
from decimal import Decimal
from app.stock_adjustments.costing import QTY_Q, MONEY_Q, ZERO
from app.stock_adjustments.models import StockMovement

LifoLayer = namedtuple('LifoLayer', ['received_at', 'qty', 'unit_cost'])
LifoCogsLine = namedtuple('LifoCogsLine', [
    'movement_id', 'date', 'quantity', 'lifo_unit_cost', 'lifo_cost',
    'actual_unit_cost', 'actual_cost', 'variance'])


def _replay(product_id, branch_id, end_date=None):
    """Walk this product/branch's real StockMovement history in chronological
    order, simulating a LIFO stack purely in memory -- nothing here is ever
    persisted. Returns (final_layers, cogs_lines):

    final_layers -- the stack's state at the end of the walk (or as of
    end_date, if given): a list of LifoLayer(received_at, qty, unit_cost).
    A negative qty entry is an exhaustion deficit (mirrors 2b's own
    fifo_plan_consume convention) -- there is no persistent state to
    reconcile it against, so unlike 2b's real engine, no pay-down mechanism
    is needed: a later IN movement in the SAME replay just pushes a new
    layer on top, and a later OUT movement pops it under normal LIFO order.

    cogs_lines -- one LifoCogsLine per OUT movement encountered across the
    WHOLE walk (not date-filtered here -- lifo_cogs_for_range filters this
    list itself, since the walk must still process every earlier movement
    to get the stack's state entering any given date correct).
    """
    query = StockMovement.query.filter_by(product_id=product_id, branch_id=branch_id)
    if end_date is not None:
        end_inclusive = datetime.combine(end_date, time.max)
        query = query.filter(StockMovement.created_at <= end_inclusive)
    movements = query.order_by(StockMovement.created_at, StockMovement.id).all()

    stack = []          # list of dicts; index -1 is the LIFO top (most recently pushed)
    cogs_lines = []
    last_cost = ZERO    # the most recent cost touched -- exhaustion-deficit fallback basis

    for mv in movements:
        qty = Decimal(mv.quantity)
        if qty > ZERO:
            cost = Decimal(mv.unit_cost)
            stack.append({'qty': qty, 'unit_cost': cost, 'received_at': mv.created_at})
            last_cost = cost
        elif qty < ZERO:
            need = -qty
            total_cost = ZERO
            while need > ZERO and stack:
                top = stack[-1]
                take = min(top['qty'], need)
                total_cost += take * top['unit_cost']
                last_cost = top['unit_cost']
                top['qty'] -= take
                need -= take
                if top['qty'] <= ZERO:
                    stack.pop()
            if need > ZERO:
                total_cost += need * last_cost
                stack.append({'qty': -need, 'unit_cost': last_cost, 'received_at': mv.created_at})
            actual_cost = (-qty * Decimal(mv.unit_cost)).quantize(MONEY_Q)
            lifo_cost = total_cost.quantize(MONEY_Q)
            lifo_unit_cost = (total_cost / -qty).quantize(MONEY_Q) if qty != ZERO else ZERO
            cogs_lines.append(LifoCogsLine(
                movement_id=mv.id, date=mv.created_at, quantity=(-qty).quantize(QTY_Q),
                lifo_unit_cost=lifo_unit_cost, lifo_cost=lifo_cost,
                actual_unit_cost=Decimal(mv.unit_cost), actual_cost=actual_cost,
                variance=(lifo_cost - actual_cost).quantize(MONEY_Q)))
        # qty == 0 movements don't occur in practice; skipped defensively

    final_layers = [LifoLayer(received_at=e['received_at'], qty=e['qty'].quantize(QTY_Q),
                              unit_cost=e['unit_cost']) for e in stack]
    return final_layers, cogs_lines


def current_lifo_valuation(product_id, branch_id, as_of_date=None):
    """Read-only. The LIFO stack's state as of as_of_date (or "now" -- i.e.
    every movement to date -- if None)."""
    layers, _ = _replay(product_id, branch_id, end_date=as_of_date)
    return layers
