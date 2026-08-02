"""Production Run lifecycle (R-07 Process Track slice P2).

Mirrors work_orders/service.py's shape. Opening a run snapshots the BOM's component
lines onto ProductionRunMaterial so a later BOM edit never disturbs a run already
under way -- the same rule release_work_order() applies on the Discrete side.
"""
from decimal import Decimal

from app.bill_of_materials.service import consume_materials
from app.production_runs.models import ProductionRunMaterial


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
