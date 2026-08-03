"""Cost of Production Report for a Production Run (R-07 Process Track slice P5).

Process costing's actual deliverable: a three-schedule statement that reconciles
units and costs for one closed period. Deliberately NOT a mirror of D5's Work
Order list -- a Work Order is a job with a unit cost, a Production Run is a period
over a department, and the domain's statement is this one. See
docs/superpowers/specs/2026-08-03-r07-p5-production-run-cost-report-design.md.

WHERE THE FIGURES COME FROM, and why that matters:

    material added      Sum of WIP DEBITS on the run's manufacturing_consumption JEs
    conversion applied  Sum of WIP DEBITS on its manufacturing_conversion JE
    transferred out     Sum of WIP CREDITS on its manufacturing_production JE
    beginning WIP       run.beginning_wip_cost  (carried forward; no JE represents it)
    ending WIP          run.ending_wip_cost     (frozen at close)

Three of the five come straight off the ledger, so "costs accounted for == costs
to account for" reconciles the WIP control account -- it is not the report
agreeing with itself. It CAN fail, and that is the point: if the run record has
been edited since it closed, or a posting is missing, the difference shows here.

NON-NEGOTIABLE: this module must not call compute_run_costing(). That is the live
PREVIEW engine used by the run detail page for OPEN runs, and it reads
run.conversion_cost / run.beginning_wip_cost as stored values. Using it here would
make the statement agree with the run record rather than with the GL, turning a
tie-out into a restatement. equivalent_units() IS shared, legitimately -- no
journal entry carries a unit count.
"""
from decimal import Decimal

from app.journal_entries.models import JournalEntry
from app.posting.control_accounts import get_control_account
from app.production_runs.costing import equivalent_units
from app.production_runs.models import ProductionRun

ZERO = Decimal('0.00')
MONEY = Decimal('0.01')
QTY = Decimal('0.0001')


def _wip_sums_by_entry_type(run):
    """(debits, credits) against the WIP control account, keyed by entry_type.

    Returns zeros for every type when WIP is unassigned rather than raising -- a
    half-configured install should see a statement of zeros, not a 500 (D5's
    convention via get_control_account(..., required=False)).
    """
    debits = {}
    credits = {}
    wip = get_control_account('wip', required=False)
    if wip is None:
        return debits, credits
    jes = JournalEntry.query.filter_by(reference=run.run_number).all()
    for je in jes:
        if je.entry_type not in ('manufacturing_consumption', 'manufacturing_conversion',
                                 'manufacturing_production'):
            continue
        for line in je.lines:
            if line.account_id != wip.id:
                continue
            debits[je.entry_type] = debits.get(je.entry_type, ZERO) + (line.debit_amount or ZERO)
            credits[je.entry_type] = credits.get(je.entry_type, ZERO) + (line.credit_amount or ZERO)
    return debits, credits


def generate_production_run_cost_report(run_id, branch_id):
    """The statement for one CLOSED run, scoped to branch_id.

    Raises ValueError for a run that is not closed or not in this branch -- an open
    run has no frozen figures and no transfer posting, so its "costs accounted for"
    would be meaningless. The run detail page's live costing panel (P3) already
    serves the preview need.
    """
    run = ProductionRun.query.filter_by(id=run_id, branch_id=branch_id).first()
    if run is None:
        raise ValueError('That Production Run does not exist in this branch.')
    if run.status != 'closed':
        raise ValueError('A Cost of Production Report is only available for a closed '
                         'Production Run.')

    debits, credits = _wip_sums_by_entry_type(run)
    material_added = debits.get('manufacturing_consumption', ZERO).quantize(MONEY)
    conversion_applied = debits.get('manufacturing_conversion', ZERO).quantize(MONEY)
    # The WIP CREDIT, not the Inventory debit: for a standard-costed output those
    # differ by the variance leg, and WIP is what this statement is reconciling.
    transferred_out = credits.get('manufacturing_production', ZERO).quantize(MONEY)
    # A cancellation reversal posts WIP credits under manufacturing_consumption; a
    # cancelled run can never reach here (status must be 'closed'), so the
    # consumption credits are not netted off -- keep it that way rather than
    # silently absorbing a shape that should be impossible.

    beginning_wip_cost = Decimal(str(run.beginning_wip_cost or 0)).quantize(MONEY)
    ending_wip_cost = Decimal(str(run.ending_wip_cost or 0)).quantize(MONEY)

    total_to_account_for = (beginning_wip_cost + material_added + conversion_applied).quantize(MONEY)
    total_accounted_for = (transferred_out + ending_wip_cost).quantize(MONEY)
    difference = (total_to_account_for - total_accounted_for).quantize(MONEY)

    eu = equivalent_units(run)

    beginning_units = Decimal(str(run.beginning_wip_units or 0)).quantize(QTY)
    started = Decimal(str(run.units_started or 0)).quantize(QTY)
    completed = Decimal(str(run.units_completed_and_transferred or 0)).quantize(QTY)
    ending_units = Decimal(str(run.units_ending_wip or 0)).quantize(QTY)
    units_to_account_for = (beginning_units + started).quantize(QTY)
    units_accounted_for = (completed + ending_units).quantize(QTY)

    return {
        'run': run,
        # quantity schedule
        'beginning_wip_units': beginning_units,
        'units_started': started,
        'units_to_account_for': units_to_account_for,
        'units_completed_and_transferred': completed,
        'units_ending_wip': ending_units,
        'units_accounted_for': units_accounted_for,
        # POSITIVE = ordinary shrinkage (dehydration loses mass); NEGATIVE = more
        # units accounted for than ever existed, i.e. a data error. The sign is
        # returned raw -- deciding which one to flag is the template's job.
        'unaccounted_units': (units_to_account_for - units_accounted_for).quantize(QTY),
        'ending_wip_pct_complete': run.ending_wip_pct_complete,
        # equivalent units
        'equivalent_units': eu,
        'cost_per_equivalent_unit': run.transferred_unit_cost,
        # costs to account for
        'beginning_wip_cost': beginning_wip_cost,
        'material_added': material_added,
        'conversion_applied': conversion_applied,
        'total_to_account_for': total_to_account_for,
        # costs accounted for
        'transferred_out': transferred_out,
        'ending_wip_cost': ending_wip_cost,
        'total_accounted_for': total_accounted_for,
        'difference': difference,
        'reconciles': difference == ZERO,
    }
