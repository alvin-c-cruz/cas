"""Weighted-average equivalent-units costing for a Production Run (R-07 P3).

    equivalent units = units_completed_and_transferred
                     + (units_ending_wip x ending_wip_pct_complete / 100)
    cost per EU      = (material cost + conversion cost) / equivalent units

Material cost is read back off the run's posted `manufacturing_consumption` journal
entries -- specifically the WIP debits -- and never recomputed from
ProductionRunMaterial.quantity_issued. That is the same rule D5's Work Order costing
report follows: the reported figure reconciles to the GL by construction, so a
tampered or drifted child row cannot change it.

Conversion cost is entered manually on the run (owner decision 2026-08-02). The arc
spec originally said to reuse R-03a's ExpenseAllocationRule; that is impossible --
it is a product-line driver with no department or period dimension. See the dated
correction in docs/superpowers/specs/2026-07-19-manufacturing-r07-design.md.
"""
from decimal import Decimal, ROUND_HALF_UP

from app.journal_entries.models import JournalEntry
from app.posting.control_accounts import get_control_account

ZERO = Decimal('0.00')
QTY = Decimal('0.0001')
MONEY = Decimal('0.01')


def _material_cost(run):
    """Sum of the WIP debits across every manufacturing_consumption JE for this run."""
    wip = get_control_account('wip', required=False)
    if wip is None:
        return ZERO
    jes = JournalEntry.query.filter_by(
        entry_type='manufacturing_consumption', reference=run.run_number).all()
    total = ZERO
    for je in jes:
        for line in je.lines:
            if line.account_id == wip.id:
                total += (line.debit_amount or ZERO)
    return total.quantize(MONEY)


def equivalent_units(run):
    """Completed-and-transferred units plus the completed FRACTION of ending WIP.

    A single ending_wip_pct_complete covers both materials and conversion -- the
    deliberate simplification recorded in the arc design, extendable later if a real
    customer process needs the split.
    """
    completed = Decimal(str(run.units_completed_and_transferred or 0))
    wip_units = Decimal(str(run.units_ending_wip or 0))
    pct = Decimal(str(run.ending_wip_pct_complete or 0))
    return (completed + (wip_units * pct / Decimal('100'))).quantize(QTY)


def compute_run_costing(run):
    """Costing figures for one Production Run. Never raises on an incomplete run --
    a period with nothing reported yet returns cost_per_equivalent_unit=None rather
    than dividing by zero.

    The cost pool is BEGINNING WIP BROUGHT FORWARD + costs added this period (R-07
    P4). P3 shipped with the pool reading only this run's own posted JEs, which is
    right for a first period and understates every period after it by exactly what
    the predecessor left in WIP -- value that would otherwise sit stranded in the
    control account with nothing ever relieving it.

    Beginning-WIP UNITS deliberately do NOT enter equivalent units: under weighted
    average those units are already counted in units_completed_and_transferred once
    they finish, so adding them again would double-count. Only the COST joins the pool.
    """
    beginning = Decimal(str(run.beginning_wip_cost or 0)).quantize(MONEY)
    material = _material_cost(run)
    conversion = Decimal(str(run.conversion_cost or 0)).quantize(MONEY)
    total = (beginning + material + conversion).quantize(MONEY)
    eu = equivalent_units(run)
    per_eu = None
    if eu > 0:
        per_eu = (total / eu).quantize(MONEY, rounding=ROUND_HALF_UP)
    return {
        'beginning_wip_cost': beginning,
        'material_cost': material,
        'conversion_cost': conversion,
        'total_cost': total,
        'equivalent_units': eu,
        'cost_per_equivalent_unit': per_eu,
    }
