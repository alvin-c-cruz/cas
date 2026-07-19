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
