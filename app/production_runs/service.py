"""Production Run lifecycle (R-07 Process Track slice P2).

Mirrors work_orders/service.py's shape. Opening a run snapshots the BOM's component
lines onto ProductionRunMaterial so a later BOM edit never disturbs a run already
under way -- the same rule release_work_order() applies on the Discrete side.
"""
from decimal import Decimal

from app.bill_of_materials.service import consume_materials
from app.production_runs.models import ProductionRun, ProductionRunMaterial

ZERO = Decimal('0.00')


def find_predecessor_run(bom_id, department_id, branch_id, period_start):
    """The most recent CLOSED run for the same cost pool ending before *period_start*.

    "Same cost pool" is (bom, department, branch): a different product line, a
    different department, or another branch accumulates its own WIP, so carrying
    across any of them would move value between pools that never touched.

    Only a CLOSED run qualifies. An OPEN one has not settled its ending WIP -- that
    figure is still moving, and is not even frozen yet. A CANCELLED one reversed its
    consumptions and therefore left nothing in WIP at all.

    period_end must be strictly BEFORE period_start; an overlapping run is not a
    predecessor, it is a double count.
    """
    return (ProductionRun.query
            .filter(ProductionRun.bom_id == bom_id,
                    ProductionRun.department_id == department_id,
                    ProductionRun.branch_id == branch_id,
                    ProductionRun.status == 'closed',
                    ProductionRun.period_end < period_start)
            .order_by(ProductionRun.period_end.desc(), ProductionRun.id.desc())
            .first())


def carry_beginning_wip(run):
    """Stamp *run*'s beginning WIP from its predecessor, or leave it at zero.

    PULLED here at create time rather than PUSHED at the predecessor's close: when a
    run closes, its successor usually does not exist yet, because the accountant
    closes the old period before opening the new one.

    What carries is the predecessor's units_ending_wip and its frozen
    ending_wip_cost -- the residual plug left sitting in the WIP account. A run
    closed before P4 shipped has no ending_wip_cost at all; that reads as zero, never
    NULL, since NULL would drop out of the cost pool's sum instead of adding nothing.
    """
    prior = find_predecessor_run(run.bom_id, run.department_id, run.branch_id,
                                 run.period_start)
    if prior is None:
        run.beginning_wip_units = Decimal('0')
        run.beginning_wip_cost = ZERO
        return None
    run.beginning_wip_units = Decimal(str(prior.units_ending_wip or 0))
    run.beginning_wip_cost = Decimal(str(prior.ending_wip_cost or 0)).quantize(ZERO)
    return prior


def snapshot_materials(run):
    """Copy the BOM's component lines onto the run, scaled by units_started."""
    if not run.bom.lines:
        raise ValueError('This Bill of Materials has no component lines -- nothing to produce.')
    for line in run.bom.lines:
        run.materials.append(ProductionRunMaterial(
            line_number=line.line_number,
            component_product_id=line.component_product_id,
            quantity_required=line.quantity_per * run.units_started,
            uom_id=line.uom_id,
        ))


def issue_material(material, quantity, actor):
    """Consume `quantity` of one snapshotted component into WIP.

    Posts Dr wip / Cr inventory through the shared consume_materials() seam (which
    accepts a ProductionRun since P2 Task 2). Does NOT commit -- the caller owns the
    transaction, same contract as the Discrete track's issue_material.
    """
    run = material.run
    if run.status != 'open':
        raise ValueError('Materials can only be issued to an open Production Run.')
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValueError('Issue quantity must be greater than zero.')
    remaining = Decimal(str(material.quantity_required)) - Decimal(str(material.quantity_issued or 0))
    if quantity > remaining:
        raise ValueError(
            f'Cannot issue {quantity} -- only {remaining} of '
            f'{material.component_product.code} remains required for this run.')

    consume_materials(run, [(material, quantity)], actor)
    material.quantity_issued = Decimal(str(material.quantity_issued or 0)) + quantity
