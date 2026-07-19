"""Audit-log coverage for Work Order create/release/cancel (R-07 D2)."""
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.audit.models import AuditLog
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_create_and_release_log_audit_entries(client, accountant_user, db_session, main_branch):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()
    out = Product(code='WOA-OUT', name='Out', is_active=True)
    comp = Product(code='WOA-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=1))
    db.session.add(bom); db.session.commit()
    _login(client, accountant_user, main_branch)
    client.post('/work-orders/create', data={'bom_id': bom.id, 'qty_to_produce': '3'},
               follow_redirects=True)
    from app.work_orders.models import WorkOrder
    wo = WorkOrder.query.filter_by(bom_id=bom.id).one()
    client.post(f'/work-orders/{wo.id}/release', follow_redirects=True)

    create_entry = AuditLog.query.filter_by(module='work_orders', action='create').first()
    assert create_entry is not None and create_entry.record_identifier == wo.wo_number
    release_entry = AuditLog.query.filter_by(module='work_orders', action='update').first()
    assert release_entry is not None


def test_start_complete_issue_log_audit_entries(client, accountant_user, db_session, main_branch):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()
    from app.work_centers.models import WorkCenter
    wc = WorkCenter(branch_id=main_branch.id, code='AUV-WC', name='Line')
    db.session.add(wc); db.session.commit()
    out = Product(code='AUV-OUT', name='Out', is_active=True)
    comp = Product(code='AUV-COMP', name='Comp', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id, quantity_per=1))
    db.session.add(bom); db.session.commit()
    from app.bill_of_materials.models import BillOfMaterialOperation
    bom.operations.append(BillOfMaterialOperation(sequence_no=1, work_center_id=wc.id, operation_name='Cut'))
    db.session.commit()
    _login(client, accountant_user, main_branch)
    client.post('/work-orders/create', data={'bom_id': bom.id, 'qty_to_produce': '3'}, follow_redirects=True)
    from app.work_orders.models import WorkOrder
    wo = WorkOrder.query.filter_by(bom_id=bom.id).one()
    client.post(f'/work-orders/{wo.id}/release', follow_redirects=True)
    db.session.refresh(wo)
    op = wo.operations[0]

    client.post(f'/work-orders/{wo.id}/operations/{op.id}/start', follow_redirects=True)
    client.post(f'/work-orders/{wo.id}/operations/{op.id}/complete', follow_redirects=True)

    entries = AuditLog.query.filter_by(module='work_orders', action='update').all()
    notes_or_new = [e.new_values for e in entries]
    assert any('in_progress' in str(v) for v in notes_or_new)
    assert any('complete' in str(v) for v in notes_or_new)
