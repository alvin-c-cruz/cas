"""release_work_order() -- the D2 snapshot action. Copies the BillOfMaterial's
lines/operations onto WorkOrderMaterial/WorkOrderOperation rows attached to the
same WorkOrder, then flips status to 'released'. A later BOM edit never
disturbs a job already released -- same snapshot-at-creation rule as Wave 0's
own BillOfMaterialLine/Operation copy from BOM to itself, one level up."""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.bill_of_materials.service import consume_materials
from app.work_orders.models import WorkOrderMaterial, WorkOrderOperation, WorkOrderCompletion
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_entry_number
from app.stock_adjustments.service import reverse_document_movements, post_movement
from app.posting.control_accounts import get_control_account

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


def _check_all_operations_complete(wo):
    outstanding = [op.operation_name for op in wo.operations if op.status != 'complete']
    if outstanding:
        raise ValueError(
            'All operations must be complete before this Work Order can be completed -- '
            f'still outstanding: {", ".join(outstanding)}.')


def _materials_in_wip_total(wo, wip_account_id):
    """Sum of every manufacturing_consumption JE's WIP debit lines posted for
    this Work Order -- the REAL, actual material cost issued so far (D3's
    issue_material -> consume_materials chain), not a planned/BOM figure."""
    originals = (JournalEntry.query
                .filter_by(entry_type='manufacturing_consumption', reference=wo.wo_number)
                .all())
    total = ZERO
    for je in originals:
        for line in je.lines:
            if line.account_id == wip_account_id:
                total += Decimal(line.debit_amount)
    return total


def _labor_total_cost(wo):
    """Sum of actual_minutes/60 x hourly_rate across every operation --
    fully deterministic once all operations are complete (actual_minutes
    never changes after complete_operation() sets it once), so safe to
    recompute on every call. Raises if any operation's work center has no
    hourly rate assigned -- fail closed rather than silently costing labor
    at zero."""
    total = ZERO
    for op in wo.operations:
        if op.work_center.hourly_rate is None:
            raise ValueError(
                f'Work Center "{op.work_center.code}" has no hourly rate assigned -- '
                f'set one before completing this Work Order.')
        total += (Decimal(op.actual_minutes) / Decimal('60')) * Decimal(op.work_center.hourly_rate)
    return total.quantize(Decimal('0.01'))


def _ensure_actual_unit_cost(wo):
    """Compute + freeze WorkOrder.actual_unit_cost the first time all
    operations are complete. A no-op once already set -- every batch after
    the first reuses the SAME frozen figure, so cost-per-unit never drifts
    between batches of the same job. Does NOT commit."""
    _check_all_operations_complete(wo)
    if wo.actual_unit_cost is not None:
        return
    wip_account = get_control_account('wip')
    materials_total = _materials_in_wip_total(wo, wip_account.id)
    labor_total = _labor_total_cost(wo)
    total_actual_cost = materials_total + labor_total
    wo.actual_unit_cost = (total_actual_cost / wo.qty_to_produce).quantize(Decimal('0.01'))


def complete_work_order_batch(wo, batch_qty, actor):
    """Post one completion batch: produce batch_qty of the WO's finished good
    at the WO's frozen actual_unit_cost, relieving WIP (material portion) and
    Labor-Applied (labor portion) proportionally, plus a standard-costing
    variance leg when the finished good is standard-costed. Auto-transitions
    the WO to 'completed' once the running total reaches qty_to_produce. Does
    NOT commit -- caller owns the transaction."""
    if wo.status not in ('released', 'in_progress'):
        raise ValueError('Only a released or in-progress Work Order can be completed.')
    batch_qty = Decimal(batch_qty)
    if batch_qty <= ZERO:
        raise ValueError('Batch quantity must be greater than zero.')
    remaining = wo.qty_to_produce - wo.qty_completed_to_date
    if batch_qty > remaining:
        raise ValueError(f'Cannot complete more than the remaining outstanding quantity ({remaining}).')

    _ensure_actual_unit_cost(wo)

    labor_unit_cost = (_labor_total_cost(wo) / wo.qty_to_produce).quantize(Decimal('0.01'))
    material_unit_cost = wo.actual_unit_cost - labor_unit_cost

    product = wo.bom.product
    inv_account = get_control_account('inventory')
    wip_account = get_control_account('wip')
    labor_account = get_control_account('labor_applied')

    je = _new_je(generate_entry_number(wo.branch_id), ph_now().date(),
                 f'Work Order {wo.wo_number} completion', wo.wo_number, wo.branch_id, actor)

    mv, _went_negative = post_movement(
        product, wo.branch_id, 'production', batch_qty, wo.actual_unit_cost,
        'work_order', wo.id, f'{wo.wo_number} completion batch', actor, journal_entry_id=je.id)

    inventory_amount = (batch_qty * wo.actual_unit_cost).quantize(Decimal('0.01'))
    material_amount = (batch_qty * material_unit_cost).quantize(Decimal('0.01'))
    labor_amount = (inventory_amount - material_amount).quantize(Decimal('0.01'))

    n = 1
    _add_line(je, n, inv_account.id, f'{product.code} produced', inventory_amount, ZERO); n += 1
    _add_line(je, n, wip_account.id, f'{product.code} relieved from WIP', ZERO, material_amount); n += 1
    _add_line(je, n, labor_account.id, f'{product.code} labor applied', ZERO, labor_amount); n += 1

    if product.costing_method == 'standard':
        variance = (inventory_amount - batch_qty * Decimal(mv.unit_cost)).quantize(Decimal('0.01'))
        if variance != ZERO:
            variance_account = get_control_account('inventory_variance')
            if variance > ZERO:
                _add_line(je, n, variance_account.id, f'{product.code} standard cost variance', variance, ZERO); n += 1
                _add_line(je, n, inv_account.id, f'{product.code} standard cost variance', ZERO, variance); n += 1
            else:
                _add_line(je, n, inv_account.id, f'{product.code} standard cost variance', -variance, ZERO); n += 1
                _add_line(je, n, variance_account.id, f'{product.code} standard cost variance', ZERO, -variance); n += 1

    db.session.flush()
    je.calculate_totals()
    if not je.is_balanced:
        raise ValueError(f'{wo.wo_number} completion JE does not balance '
                         f'(debit={je.total_debit}, credit={je.total_credit}).')

    completion = WorkOrderCompletion(work_order_id=wo.id, qty_completed=batch_qty,
                                     unit_cost=wo.actual_unit_cost, journal_entry_id=je.id,
                                     completed_by_id=actor.id, completed_at=ph_now())
    db.session.add(completion)

    wo.qty_completed_to_date += batch_qty
    if wo.qty_completed_to_date >= wo.qty_to_produce:
        wo.status = 'completed'
    return completion


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
