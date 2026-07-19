"""Routing (BillOfMaterialOperation) tests -- discrete-mode BOMs only (R-07 D1)."""
from decimal import Decimal
import pytest
from app import db
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialOperation
from app.products.models import Product
from app.utils.cache_helpers import clear_product_cache
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


def _bom(db_session, main_branch, mode='discrete'):
    p = Product(code='ROUTE-P1', name='Can Product', is_active=True)
    db.session.add(p); db.session.commit()
    clear_product_cache()
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


import json


def test_parse_and_attach_operations(db_session, main_branch):
    from app.bill_of_materials.forms import _parse_and_attach_bom_operations
    bom = _bom(db_session, main_branch)
    wc = _work_center(db_session, main_branch)
    ops_json = json.dumps([{'work_center_id': wc.id, 'operation_name': 'Forming',
                            'standard_time_minutes': '5.50'}])
    _parse_and_attach_bom_operations(bom, ops_json)
    db.session.commit()
    assert len(bom.operations) == 1
    assert bom.operations[0].sequence_no == 1
    assert bom.operations[0].operation_name == 'Forming'


def test_parse_skips_blank_trailing_operation(db_session, main_branch):
    from app.bill_of_materials.forms import _parse_and_attach_bom_operations
    bom = _bom(db_session, main_branch)
    wc = _work_center(db_session, main_branch)
    ops_json = json.dumps([
        {'work_center_id': wc.id, 'operation_name': 'Forming', 'standard_time_minutes': '5.50'},
        {'work_center_id': None, 'operation_name': '', 'standard_time_minutes': None},
    ])
    _parse_and_attach_bom_operations(bom, ops_json)
    assert len(bom.operations) == 1


def test_create_discrete_bom_with_routing(client, accountant_user, db_session, main_branch):
    from app import db as _db
    from app.products.models import Product
    from app.settings import AppSettings
    from app.audit.models import AuditLog
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    AppSettings.set_setting('manufacturing_discrete_enabled', '1')
    db_session.commit()
    out = Product(code='ROUTE-OUT', name='Out', is_active=True)
    _db.session.add(out); _db.session.commit()
    clear_product_cache()
    wc = _work_center(db_session, main_branch, code='ROUTE-WC2')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(accountant_user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id
    resp = client.post('/bill-of-materials/new', data={
        'product_id': out.id, 'manufacturing_mode': 'discrete', 'lines': '[]',
        'operations': json.dumps([{'work_center_id': wc.id, 'operation_name': 'Forming',
                                   'standard_time_minutes': '5.50'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.bill_of_materials.models import BillOfMaterial
    bom = BillOfMaterial.query.filter_by(product_id=out.id).one()
    assert len(bom.operations) == 1
    entry = AuditLog.query.filter_by(module='bill_of_materials', action='create').first()
    assert entry is not None
