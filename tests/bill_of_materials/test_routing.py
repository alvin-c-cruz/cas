"""Routing (BillOfMaterialOperation) tests -- discrete-mode BOMs only (R-07 D1)."""
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialOperation
from app.products.models import Product
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


def _bom(db_session, main_branch, mode='discrete'):
    p = Product(code='ROUTE-P1', name='Can Product', is_active=True)
    db.session.add(p); db.session.commit()
    bom = BillOfMaterial(product_id=p.id, manufacturing_mode=mode)
    db.session.add(bom); db.session.commit()
    return bom


def _work_center(db_session, main_branch, code='ROUTE-WC1'):
    wc = WorkCenter(branch_id=main_branch.id, code=code, name='Line 1')
    db.session.add(wc); db.session.commit()
    return wc


def test_operations_ordered_by_sequence(db_session, main_branch):
    bom = _bom(db_session, main_branch)
    wc = _work_center(db_session, main_branch)
    bom.operations.append(BillOfMaterialOperation(sequence_no=2, work_center_id=wc.id,
                                                   operation_name='Seaming'))
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id,
                                                   operation_name='Forming'))
    db.session.commit()
    assert [op.operation_name for op in bom.operations] == ['Forming', 'Seaming']


def test_operations_cascade_delete_with_bom(db_session, main_branch):
    bom = _bom(db_session, main_branch)
    wc = _work_center(db_session, main_branch)
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id,
                                                   operation_name='Forming',
                                                   standard_time_minutes=Decimal('5.50')))
    db.session.commit()
    op_id = bom.operations[0].id
    db.session.delete(bom)
    db.session.commit()
    assert db.session.get(BillOfMaterialOperation, op_id) is None
