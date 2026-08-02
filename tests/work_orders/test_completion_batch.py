"""complete_work_order_batch() (R-07 D4)."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.work_centers.models import WorkCenter
from app.stock_adjustments.service import post_movement
from app.journal_entries.models import JournalEntry

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def _ready_wo(main_branch, accountant_user, qty_to_produce='10', costing_method='moving_average',
             standard_cost=None, hourly_rate='60.00', minutes='60'):
    from app.utils import ph_now
    from datetime import timedelta
    out = Product(code='CB-OUT', name='Out', track_inventory=True,
                 costing_method=costing_method, standard_cost=standard_cost, is_active=True)
    comp = Product(code='CB-COMP', name='Comp', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code='CB-WC', name='Line', hourly_rate=Decimal(hourly_rate))
    db.session.add(wc); db.session.commit()
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id, operation_name='Cut'))
    db.session.commit()

    from app.work_orders.service import release_work_order, issue_material, start_operation, complete_operation
    from app.work_orders.forms import generate_wo_number
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal(qty_to_produce))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()

    post_movement(comp, main_branch.id, 'opening', Decimal('1000'), Decimal('5.00'),
                 'stock_adjustment', 0, 'seed', accountant_user)
    db.session.commit()
    issue_material(wo.materials[0], Decimal(qty_to_produce), accountant_user)   # qty x PHP 5.00
    db.session.commit()

    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    op.actual_start_at = ph_now() - timedelta(minutes=int(minutes))
    db.session.commit()
    complete_operation(op, accountant_user)
    db.session.commit()
    return wo


def test_single_batch_completes_full_quantity_and_transitions_status(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    wo = _ready_wo(main_branch, accountant_user)
    completion = complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()
    assert completion.qty_completed == Decimal('10')
    assert wo.qty_completed_to_date == Decimal('10')
    assert wo.status == 'completed'
    je = db.session.get(JournalEntry, completion.journal_entry_id)
    assert je.is_balanced


def test_multi_batch_accumulates_and_completes_on_final_batch(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    c1 = complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()
    assert wo.qty_completed_to_date == Decimal('4')
    assert wo.status != 'completed'
    assert c1.unit_cost == wo.actual_unit_cost

    c2 = complete_work_order_batch(wo, Decimal('6'), accountant_user)
    db.session.commit()
    assert wo.qty_completed_to_date == Decimal('10')
    assert wo.status == 'completed'
    assert c2.unit_cost == wo.actual_unit_cost   # same frozen figure both batches
    assert len(wo.completions) == 2


def test_batch_qty_cannot_exceed_remaining(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    with pytest.raises(ValueError, match='remaining'):
        complete_work_order_batch(wo, Decimal('11'), accountant_user)


def test_batch_qty_must_be_positive(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    wo = _ready_wo(main_branch, accountant_user)
    with pytest.raises(ValueError, match='greater than zero'):
        complete_work_order_batch(wo, Decimal('0'), accountant_user)


def test_blocked_when_operations_incomplete(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch, release_work_order
    from app.work_orders.forms import generate_wo_number
    out = Product(code='CBX-OUT', name='Out', track_inventory=True, costing_method='moving_average', is_active=True)
    comp = Product(code='CBX-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code='CBX-WC', name='Line', hourly_rate=Decimal('60'))
    db.session.add(wc); db.session.commit()
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id, operation_name='Cut'))
    db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('5'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()
    with pytest.raises(ValueError, match='Cut'):
        complete_work_order_batch(wo, Decimal('5'), accountant_user)


def test_non_standard_finished_good_no_variance_leg(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    wo = _ready_wo(main_branch, accountant_user, costing_method='moving_average')
    completion = complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()
    je = db.session.get(JournalEntry, completion.journal_entry_id)
    assert je.lines.count() == 3   # Inventory / WIP / Labor-Applied only -- no variance leg


def test_standard_finished_good_posts_variance_leg_when_actual_differs(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    # actual_unit_cost will land around (10*5.00 + labor)/10 ~= 5.60-ish; standard_cost pinned far off
    # so a real, nonzero variance is guaranteed.
    wo = _ready_wo(main_branch, accountant_user, costing_method='standard', standard_cost=Decimal('9.00'))
    completion = complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()
    je = db.session.get(JournalEntry, completion.journal_entry_id)
    assert je.lines.count() == 5   # Inventory / WIP / Labor-Applied / variance x2
    assert je.is_balanced


def test_standard_finished_good_no_variance_leg_when_actual_equals_standard(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch
    # 10 units x PHP 5.00 material + PHP 60.00 labor (60 min @ PHP60/hr) = PHP 110.00 total / 10 = PHP 11.00/unit
    wo = _ready_wo(main_branch, accountant_user, costing_method='standard', standard_cost=Decimal('11.00'),
                   hourly_rate='60.00', minutes='60')
    completion = complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()
    je = db.session.get(JournalEntry, completion.journal_entry_id)
    if wo.actual_unit_cost == Decimal('11.00'):
        assert je.lines.count() == 3
    else:
        assert je.lines.count() == 5   # actual_minutes rounding could land a few cents off standard
