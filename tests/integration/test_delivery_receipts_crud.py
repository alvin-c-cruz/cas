import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _confirmed_so(db_session, branch_id):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-C-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=branch_id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    return so


def test_create_draft_dr_persists_and_snapshots_customer(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    assert dr is not None and dr.status == 'draft'
    assert dr.customer_name == 'Acme' and dr.customer_id == so.customer_id
    assert dr.line_items[0].delivered_quantity == Decimal('4')
    assert dr.dr_number.startswith('DR-')


def test_create_dr_logs_audit_entry(client, db_session, admin_user, main_branch):
    from app.audit.models import AuditLog
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '2'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    entry = AuditLog.query.filter_by(module='delivery_receipts', record_id=dr.id).first()
    assert entry is not None and entry.action == 'create'
    assert dr.dr_number in entry.record_identifier


def test_create_dr_rejects_empty_lines(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    resp = client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': '[]'},
        follow_redirects=True)
    assert DeliveryReceipt.query.count() == 0
    assert b'at least one delivered line' in resp.data


def test_view_is_branch_scoped(client, db_session, admin_user, main_branch, branch_manila):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    assert client.get(f'/delivery-receipts/{dr.id}').status_code == 200
    with client.session_transaction() as s: s['selected_branch_id'] = branch_manila.id
    assert client.get(f'/delivery-receipts/{dr.id}').status_code == 404


def test_edit_draft_updates_quantities(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    soi_id = so.line_items[0].id
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09',
        'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '4'}])},
        follow_redirects=True)
    dr = DeliveryReceipt.query.first()
    client.post(f'/delivery-receipts/{dr.id}/edit', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-10',
        'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '6'}])},
        follow_redirects=True)
    db_session.refresh(dr)
    assert dr.line_items[0].delivered_quantity == Decimal('6')
    assert dr.delivery_date == date(2026, 7, 10)
