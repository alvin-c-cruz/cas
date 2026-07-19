"""release_work_order() tests (R-07 D2)."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine, BillOfMaterialOperation
from app.products.models import Product
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


def _bom_with_lines_and_ops(main_branch, mode='discrete', with_lines=True):
    out = Product(code='REL-OUT', name='Output', is_active=True)
    comp = Product(code='REL-COMP', name='Component', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode=mode)
    db.session.add(bom); db.session.commit()
    if with_lines:
        bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                            quantity_per=Decimal('2.5000')))
    if mode == 'discrete':
        wc = WorkCenter(branch_id=main_branch.id, code='REL-WC', name='Line')
        db.session.add(wc); db.session.commit()
        bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id,
                                                       operation_name='Forming'))
    db.session.commit()
    return bom


def test_release_snapshots_materials_and_operations(db_session, main_branch, accountant_user):
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    bom = _bom_with_lines_and_ops(main_branch)
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, accountant_user)
    db.session.commit()
    assert wo.status == 'released'
    assert len(wo.materials) == 1
    assert wo.materials[0].quantity_required == Decimal('25.0000')  # 2.5 * 10
    assert len(wo.operations) == 1
    assert wo.operations[0].operation_name == 'Forming'


def test_release_blocked_when_bom_has_no_lines(db_session, main_branch, accountant_user):
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    bom = _bom_with_lines_and_ops(main_branch, with_lines=False)
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    with pytest.raises(ValueError, match='no component lines'):
        release_work_order(wo, accountant_user)


def test_release_blocked_when_not_draft(db_session, main_branch, accountant_user):
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    bom = _bom_with_lines_and_ops(main_branch)
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'), status='released')
    db.session.add(wo); db.session.commit()
    with pytest.raises(ValueError, match='draft'):
        release_work_order(wo, accountant_user)


def test_release_process_mode_bom_snapshots_no_operations(db_session, main_branch, accountant_user):
    from app.work_orders.service import release_work_order
    from app.work_orders.forms import generate_wo_number
    bom = _bom_with_lines_and_ops(main_branch, mode='process')
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    release_work_order(wo, accountant_user)
    assert len(wo.operations) == 0
    assert len(wo.materials) == 1
