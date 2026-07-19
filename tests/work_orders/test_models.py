"""Unit tests for the WorkOrder model (R-07 Discrete Track slice D2)."""
from decimal import Decimal
import pytest
from app import db
from app.work_orders.models import WorkOrder, WorkOrderMaterial
from app.bill_of_materials.models import BillOfMaterial
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _bom(mode='discrete'):
    p = Product(code='WO-P1', name='Can Product', is_active=True)
    db.session.add(p); db.session.commit()
    bom = BillOfMaterial(product_id=p.id, manufacturing_mode=mode)
    db.session.add(bom); db.session.commit()
    return bom


def test_defaults(db_session, main_branch):
    bom = _bom()
    wo = WorkOrder(wo_number='WO-2026-07-0001', bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('100'))
    db.session.add(wo)
    db.session.commit()
    assert wo.status == 'draft'
    assert wo.row_version == 1


def test_wo_number_is_unique(db_session, main_branch):
    bom = _bom()
    db.session.add(WorkOrder(wo_number='WO-2026-07-0002', bom_id=bom.id, branch_id=main_branch.id,
                             qty_to_produce=Decimal('50')))
    db.session.commit()
    db.session.add(WorkOrder(wo_number='WO-2026-07-0002', bom_id=bom.id, branch_id=main_branch.id,
                             qty_to_produce=Decimal('25')))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_materials_cascade_delete(db_session, main_branch):
    bom = _bom()
    wo = WorkOrder(wo_number='WO-2026-07-0003', bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('10'))
    db.session.add(wo); db.session.commit()
    p2 = Product(code='WO-COMP1', name='Component', is_active=True)
    db.session.add(p2); db.session.commit()
    wo.materials.append(WorkOrderMaterial(line_number=1, component_product_id=p2.id,
                                          quantity_required=Decimal('5.0000')))
    db.session.commit()
    mat_id = wo.materials[0].id
    db.session.delete(wo)
    db.session.commit()
    assert db.session.get(WorkOrderMaterial, mat_id) is None


def test_operation_execution_columns_default(db_session, main_branch, accountant_user):
    from app.work_orders.models import WorkOrderOperation
    from app.work_centers.models import WorkCenter
    from app.work_orders.forms import generate_wo_number

    out = Product(code='WOO-OUT', name='Out', is_active=True)
    db.session.add(out); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    db.session.add(bom); db.session.commit()
    wc = WorkCenter(branch_id=main_branch.id, code='WOO-WC', name='Line')
    db.session.add(wc); db.session.commit()
    wo = WorkOrder(wo_number=generate_wo_number(), bom_id=bom.id, branch_id=main_branch.id,
                   qty_to_produce=Decimal('1'))
    db.session.add(wo); db.session.commit()
    op = WorkOrderOperation(wo_id=wo.id, sequence_no=1, work_center_id=wc.id,
                            operation_name='Cut')
    db.session.add(op); db.session.commit()

    assert op.status == 'pending'
    assert op.actual_start_at is None
    assert op.actual_complete_at is None
    assert op.actual_minutes is None
