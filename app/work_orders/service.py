"""release_work_order() -- the D2 snapshot action. Copies the BillOfMaterial's
lines/operations onto WorkOrderMaterial/WorkOrderOperation rows attached to the
same WorkOrder, then flips status to 'released'. A later BOM edit never
disturbs a job already released -- same snapshot-at-creation rule as Wave 0's
own BillOfMaterialLine/Operation copy from BOM to itself, one level up."""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.bill_of_materials.service import consume_materials
from app.work_orders.models import WorkOrderMaterial, WorkOrderOperation
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.stock_adjustments.service import reverse_document_movements

ZERO = Decimal('0.00')


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


def start_operation(operation, actor):
    if operation.status != 'pending':
        raise ValueError('Only a pending operation can be started.')
    wo = operation.work_order
    if wo.status not in ('released', 'in_progress'):
        raise ValueError('Operations can only be started on a released or in-progress Work Order.')
    operation.status = 'in_progress'
    operation.actual_start_at = ph_now()
    if wo.status == 'released':
        wo.status = 'in_progress'


def complete_operation(operation, actor):
    if operation.status != 'in_progress':
        raise ValueError('Only an in-progress operation can be completed.')
    operation.actual_complete_at = ph_now()
    complete_at = operation.actual_complete_at.replace(tzinfo=None)
    start_at = operation.actual_start_at.replace(tzinfo=None)
    delta_minutes = (complete_at - start_at).total_seconds() / 60
    operation.actual_minutes = Decimal(str(round(delta_minutes, 2)))
    operation.status = 'complete'


def issue_material(wo_material, quantity, actor):
    if quantity <= 0:
        raise ValueError('Quantity issued must be greater than zero.')
    wo = wo_material.work_order
    if wo.status not in ('released', 'in_progress'):
        raise ValueError('Materials can only be issued on a released or in-progress Work Order.')
    remaining = wo_material.quantity_required - wo_material.quantity_issued
    if quantity > remaining:
        raise ValueError(f'Cannot issue more than the remaining required quantity ({remaining}).')
    consume_materials(wo, [(wo_material, quantity)], actor)
    wo_material.quantity_issued += quantity
    if wo.status == 'released':
        wo.status = 'in_progress'


def _new_je(entry_number, entry_date, description, reference, branch_id, actor):
    je = JournalEntry(entry_number=entry_number, entry_date=entry_date, description=description,
                      reference=reference, entry_type='manufacturing_consumption', branch_id=branch_id,
                      created_by_id=actor.id, status='posted', posted_by_id=actor.id,
                      posted_at=ph_now(), is_balanced=False, total_debit=ZERO, total_credit=ZERO)
    db.session.add(je); db.session.flush()
    return je


def _add_line(je, n, account_id, description, debit, credit):
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=n, account_id=account_id,
                                    description=description, debit_amount=debit, credit_amount=credit))


def reverse_consumption(wo, actor):
    """Reverse every manufacturing_consumption JE posted for wo (there may be
    several -- one per separate issue_material call over the WO's life,
    unlike a document with a single journal_entry_id column). No-op if the
    WO never had any material issued. Does NOT commit."""
    originals = (JournalEntry.query
                .filter_by(entry_type='manufacturing_consumption', reference=wo.wo_number)
                .order_by(JournalEntry.id).all())
    if not originals:
        return

    je = _new_je(generate_entry_number(wo.branch_id), ph_now().date(),
                 f'Cancel Work Order {wo.wo_number} material consumption', wo.wo_number,
                 wo.branch_id, actor)
    n = 1
    for orig in originals:
        for line in orig.lines:
            _add_line(je, n, line.account_id, f'Cancel {wo.wo_number}',
                      line.credit_amount, line.debit_amount)   # swap Dr/Cr
            n += 1
    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'Cancel Work Order {wo.wo_number} consumption reversal JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')
    reverse_document_movements('work_order', wo.id, actor, journal_entry_id=je.id)
