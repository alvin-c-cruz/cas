"""release_work_order() -- the D2 snapshot action. Copies the BillOfMaterial's
lines/operations onto WorkOrderMaterial/WorkOrderOperation rows attached to the
same WorkOrder, then flips status to 'released'. A later BOM edit never
disturbs a job already released -- same snapshot-at-creation rule as Wave 0's
own BillOfMaterialLine/Operation copy from BOM to itself, one level up."""
from app import db
from app.work_orders.models import WorkOrderMaterial, WorkOrderOperation


def release_work_order(wo, actor):
    if wo.status != 'draft':
        raise ValueError('Only a draft Work Order can be released.')
    if not wo.bom.lines:
        raise ValueError('This Bill of Materials has no component lines -- nothing to produce.')

    for line in wo.bom.lines:
        wo.materials.append(WorkOrderMaterial(
            line_number=line.line_number,
            component_product_id=line.component_product_id,
            quantity_required=line.quantity_per * wo.qty_to_produce,
            uom_id=line.uom_id,
        ))

    if wo.bom.manufacturing_mode == 'discrete':
        for op in wo.bom.operations:
            wo.operations.append(WorkOrderOperation(
                sequence_no=op.sequence_no,
                work_center_id=op.work_center_id,
                operation_name=op.operation_name,
                standard_time_minutes=op.standard_time_minutes,
            ))

    wo.status = 'released'
