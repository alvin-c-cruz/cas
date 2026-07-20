"""Pure perpetual-costing arithmetic for the stock ledger (R-03 slice 2a-i).

No DB, no ORM -- callers pass in the current balance and the signed movement,
this returns the new balance. moving_average recomputes a weighted average on
every in-movement; standard pins the average to Product.standard_cost. fifo/
lifo/specific_identification fall back to moving_average here in 2a-i (real
layer/lot tracking is 2b/2c/2d).
"""
from decimal import Decimal

QTY_Q = Decimal('0.0001')
MONEY_Q = Decimal('0.01')
ZERO = Decimal('0')


def compute_new_balance(costing_method, old_qty, old_avg, delta_qty, in_unit_cost, standard_cost):
    """Return (new_qty, new_avg) as Decimals. delta_qty is signed (positive=in).

    standard: new_avg is always standard_cost. moving_average (and the three
    not-yet-implemented methods, which fall back to it): a positive delta
    recomputes the weighted average from in_unit_cost; a negative delta leaves
    the average untouched and issues at the current average.
    """
    old_qty = Decimal(old_qty)
    old_avg = Decimal(old_avg)
    delta_qty = Decimal(delta_qty)
    new_qty = (old_qty + delta_qty).quantize(QTY_Q)

    if costing_method == 'standard':
        new_avg = Decimal(standard_cost)
        return new_qty, new_avg.quantize(MONEY_Q)

    # moving_average (and fifo/lifo/specific_identification fallback in 2a-i)
    if delta_qty <= ZERO:
        # issue / negative adjustment: average unchanged
        return new_qty, old_avg.quantize(MONEY_Q)

    in_unit_cost = Decimal(in_unit_cost)
    denom = old_qty + delta_qty
    if denom <= ZERO:
        # starting from a zero/negative balance: the receipt cost IS the new average
        return new_qty, in_unit_cost.quantize(MONEY_Q)

    new_avg = (old_qty * old_avg + delta_qty * in_unit_cost) / denom
    return new_qty, new_avg.quantize(MONEY_Q)
