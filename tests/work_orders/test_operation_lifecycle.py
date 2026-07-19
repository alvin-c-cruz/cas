"""start_operation()/complete_operation() tests (R-07 D3)."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder, WorkOrderOperation
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


def _released_wo(main_branch):
    out = Product(code='OPX-OUT', name='Out', is_active=True)
    comp = Product(code='OPX-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=Decimal('1')))
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code='OPX-WC', name='Line')
    db.session.add(wc); db.session.commit()
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id, operation_name='Cut'))
    db.session.commit()
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('5'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, None)
    db.session.commit()
    return wo


def test_start_operation_transitions_pending_to_in_progress_and_wo_to_in_progress(db_session, main_branch, accountant_user):
    from app.work_orders.service import start_operation
    wo = _released_wo(main_branch)
    op = wo.operations[0]
    assert wo.status == 'released'
    start_operation(op, accountant_user)
    db.session.commit()
    assert op.status == 'in_progress'
    assert op.actual_start_at is not None
    assert wo.status == 'in_progress'


def test_start_operation_blocked_when_not_pending(db_session, main_branch, accountant_user):
    from app.work_orders.service import start_operation
    wo = _released_wo(main_branch)
    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    with pytest.raises(ValueError, match='pending'):
        start_operation(op, accountant_user)


def test_start_operation_blocked_when_wo_cancelled(db_session, main_branch, accountant_user):
    from app.work_orders.service import start_operation
    wo = _released_wo(main_branch)
    op = wo.operations[0]
    wo.status = 'cancelled'
    db.session.commit()
    with pytest.raises(ValueError, match='released or in-progress'):
        start_operation(op, accountant_user)


def test_complete_operation_computes_actual_minutes_from_timestamps(db_session, main_branch, accountant_user):
    from app.utils import ph_now
    from datetime import timedelta
    from app.work_orders.service import start_operation, complete_operation
    wo = _released_wo(main_branch)
    op = wo.operations[0]
    start_operation(op, accountant_user)
    db.session.commit()
    op.actual_start_at = ph_now() - timedelta(minutes=42)
    db.session.commit()
    complete_operation(op, accountant_user)
    db.session.commit()
    assert op.status == 'complete'
    assert op.actual_complete_at is not None
    assert Decimal('41.5') <= op.actual_minutes <= Decimal('42.5')


def test_complete_operation_blocked_when_not_in_progress(db_session, main_branch, accountant_user):
    from app.work_orders.service import complete_operation
    wo = _released_wo(main_branch)
    op = wo.operations[0]
    with pytest.raises(ValueError, match='in-progress'):
        complete_operation(op, accountant_user)
