"""Work Order CRUD + release/cancel + module gating tests (R-07 D2)."""
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.bill_of_materials.models import BillOfMaterial, BillOfMaterialLine
from app.products.models import Product

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()


def _bom_with_line(code='WOV-OUT'):
    out = Product(code=code, name='Output', is_active=True)
    comp = Product(code=f'{code}-C', name='Component', is_active=True)
    db.session.add_all([out, comp]); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='discrete')
    bom.lines.append(BillOfMaterialLine(line_number=1, component_product_id=comp.id,
                                        quantity_per=1))
    db.session.add(bom); db.session.commit()
    return bom


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.get('/work-orders')
    assert resp.status_code == 404


def test_create_and_release_work_order(client, accountant_user, db_session, main_branch):
    _enable(db_session)
    bom = _bom_with_line()
    _login(client, accountant_user, main_branch)
    resp = client.post('/work-orders/create', data={
        'bom_id': bom.id, 'qty_to_produce': '10',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.work_orders.models import WorkOrder
    wo = WorkOrder.query.filter_by(bom_id=bom.id).one()
    assert wo.status == 'draft'

    resp = client.post(f'/work-orders/{wo.id}/release', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(wo)
    assert wo.status == 'released'
    assert len(wo.materials) == 1


def test_cancel_requires_reason(client, accountant_user, db_session, main_branch):
    _enable(db_session)
    bom = _bom_with_line('WOV-CXL')
    _login(client, accountant_user, main_branch)
    client.post('/work-orders/create', data={'bom_id': bom.id, 'qty_to_produce': '5'},
               follow_redirects=True)
    from app.work_orders.models import WorkOrder
    wo = WorkOrder.query.filter_by(bom_id=bom.id).one()
    resp = client.post(f'/work-orders/{wo.id}/cancel', data={'cancel_reason': 'short'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(wo)
    assert wo.status == 'draft'  # rejected -- reason too short

    resp = client.post(f'/work-orders/{wo.id}/cancel',
                       data={'cancel_reason': 'Customer cancelled the order'},
                       follow_redirects=True)
    db.session.refresh(wo)
    assert wo.status == 'cancelled'


def test_wo_scoped_to_current_branch(client, admin_user, db_session, main_branch, branch_manila):
    _enable(db_session)
    bom = _bom_with_line('WOV-BR')
    _login(client, admin_user, main_branch)
    client.post('/work-orders/create', data={'bom_id': bom.id, 'qty_to_produce': '1'},
               follow_redirects=True)
    from app.work_orders.models import WorkOrder
    wo = WorkOrder.query.filter_by(bom_id=bom.id).one()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_manila.id
    resp = client.get(f'/work-orders/{wo.id}')
    assert resp.status_code == 404
