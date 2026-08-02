"""Cost-pool computation + completion-gate helpers (R-07 D4)."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def _wo_with_one_op(main_branch, hourly_rate='60.00'):
    out = Product(code='CST-OUT', name='Out', is_active=True)
    comp = Product(code='CST-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code='CST-WC', name='Line',
                    hourly_rate=Decimal(hourly_rate) if hourly_rate is not None else None)
    db.session.add(wc); db.session.commit()
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id, operation_name='Cut'))
    db.session.commit()
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()
    return wo


def test_check_all_operations_complete_raises_naming_outstanding(db_session, main_branch):
    from app.work_orders.service import _check_all_operations_complete
    wo = _wo_with_one_op(main_branch)
    with pytest.raises(ValueError, match='Cut'):
        _check_all_operations_complete(wo)


def test_check_all_operations_complete_passes_when_all_complete(db_session, main_branch, accountant_user):
    from app.work_orders.service import _check_all_operations_complete, start_operation, complete_operation
    wo = _wo_with_one_op(main_branch)
    op = wo.operations[0]
    start_operation(op, accountant_user)
    complete_operation(op, accountant_user)
    db.session.commit()
    _check_all_operations_complete(wo)  # must not raise


def test_labor_total_cost_divides_minutes_by_60(db_session, main_branch, accountant_user):
    from app.utils import ph_now
    from datetime import timedelta
    from app.work_orders.service import _labor_total_cost, start_operation, complete_operation
    wo = _wo_with_one_op(main_branch, hourly_rate='60.00')
    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    op.actual_start_at = ph_now() - timedelta(minutes=30)
    db.session.commit()
    complete_operation(op, accountant_user)
    db.session.commit()
    assert op.actual_minutes >= Decimal('29.5')
    # 30 minutes at PHP 60.00/hour = PHP 30.00, NOT PHP 1800.00 (the un-divided bug)
    assert Decimal('29.00') <= _labor_total_cost(wo) <= Decimal('31.00')


def test_labor_total_cost_raises_when_work_center_has_no_hourly_rate(db_session, main_branch, accountant_user):
    from app.work_orders.service import _labor_total_cost, start_operation, complete_operation
    wo = _wo_with_one_op(main_branch, hourly_rate=None)
    op = wo.operations[0]
    start_operation(op, accountant_user)
    complete_operation(op, accountant_user)
    db.session.commit()
    with pytest.raises(ValueError, match='hourly rate'):
        _labor_total_cost(wo)


def test_materials_in_wip_total_sums_wip_debit_lines(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import _materials_in_wip_total, issue_material
    from app.posting.control_accounts import get_control_account
    from app.products.models import Product as P
    wo = _wo_with_one_op(main_branch)
    comp = P.query.filter_by(code='CST-COMP').first()
    comp.track_inventory = True
    comp.costing_method = 'moving_average'
    db.session.commit()
    # Seed an opening balance for the component so issuing it doesn't go negative-cost.
    from app.stock_adjustments.service import post_movement
    post_movement(comp, main_branch.id, 'opening', Decimal('100'), Decimal('5.00'),
                 'stock_adjustment', 0, 'seed', accountant_user)
    db.session.commit()
    mat = wo.materials[0]
    issue_material(mat, Decimal('4'), accountant_user)
    db.session.commit()
    wip_account = get_control_account('wip')
    assert _materials_in_wip_total(wo, wip_account.id) == Decimal('20.00')  # 4 units x PHP 5.00


def test_ensure_actual_unit_cost_blocked_until_operations_complete(db_session, main_branch, wo_control_accounts):
    from app.work_orders.service import _ensure_actual_unit_cost
    wo = _wo_with_one_op(main_branch)
    with pytest.raises(ValueError, match='Cut'):
        _ensure_actual_unit_cost(wo)


def test_ensure_actual_unit_cost_computes_once_and_freezes(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.utils import ph_now
    from datetime import timedelta
    from app.work_orders.service import (_ensure_actual_unit_cost, start_operation, complete_operation,
                                         issue_material)
    from app.products.models import Product as P
    from app.stock_adjustments.service import post_movement
    wo = _wo_with_one_op(main_branch, hourly_rate='60.00')
    comp = P.query.filter_by(code='CST-COMP').first()
    comp.track_inventory = True
    comp.costing_method = 'moving_average'
    db.session.commit()
    post_movement(comp, main_branch.id, 'opening', Decimal('100'), Decimal('5.00'),
                 'stock_adjustment', 0, 'seed', accountant_user)
    db.session.commit()
    issue_material(wo.materials[0], Decimal('4'), accountant_user)   # PHP 20.00 material
    db.session.commit()
    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    op.actual_start_at = ph_now() - timedelta(minutes=30)
    db.session.commit()
    complete_operation(op, accountant_user)                          # ~PHP 30.00 labor
    db.session.commit()

    _ensure_actual_unit_cost(wo)
    db.session.commit()
    first = wo.actual_unit_cost
    assert first is not None
    assert Decimal('4.50') <= first <= Decimal('5.50')  # ~PHP 50 total / 10 qty_to_produce

    _ensure_actual_unit_cost(wo)   # calling again must NOT recompute
    db.session.commit()
    assert wo.actual_unit_cost == first
