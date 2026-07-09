import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, so_line_open_qty

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


def _create_dr(client, so, soi_id, qty):
    lines = json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': str(qty)}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    return DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()


def _branch(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


def test_approve_guard_rejects_over_open_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    dr1 = _create_dr(client, so, soi.id, 4)                       # DR#1 delivers 4
    client.post(f'/delivery-receipts/{dr1.id}/approve', follow_redirects=True)
    db_session.refresh(dr1); assert dr1.status == 'approved'

    dr2 = _create_dr(client, so, soi.id, 7)                       # open is now 6 -> 7 refused
    resp = client.post(f'/delivery-receipts/{dr2.id}/approve', follow_redirects=True)
    db_session.refresh(dr2)
    assert dr2.status == 'draft' and b'exceeds the open quantity' in resp.data

    dr3 = _create_dr(client, so, soi.id, 6)                       # exactly the open qty -> OK
    client.post(f'/delivery-receipts/{dr3.id}/approve', follow_redirects=True)
    db_session.refresh(dr3); assert dr3.status == 'approved'
    assert so_line_open_qty(soi) == Decimal('0')


def test_draft_does_not_consume_open_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    _create_dr(client, so, soi.id, 4)                             # left as draft
    assert so_line_open_qty(soi) == Decimal('10')


def test_cancel_releases_committed_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)
    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    assert so_line_open_qty(soi) == Decimal('6')
    client.post(f'/delivery-receipts/{dr.id}/cancel',
                data={'cancel_reason': 'Customer refused the delivery at the gate.'},
                follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'cancelled' and dr.cancel_reason
    assert so_line_open_qty(soi) == Decimal('10')                 # released


def test_cancel_requires_a_reason(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    resp = client.post(f'/delivery-receipts/{dr.id}/cancel', data={'cancel_reason': 'nope'},
                       follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft' and b'reason' in resp.data


def test_approved_dr_is_locked_for_edit(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)
    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)

    resp = client.post(f'/delivery-receipts/{dr.id}/edit', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-11',
        'lines': json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': '9'}])},
        follow_redirects=True)
    db_session.refresh(dr)
    assert dr.line_items[0].delivered_quantity == Decimal('4')    # unchanged
    assert dr.delivery_date == date(2026, 7, 9)
    assert b'Only a draft Delivery Receipt can be edited' in resp.data


def test_mark_delivered_stamps_actor_and_time(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft'                                   # must be approved first

    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'delivered'
    assert dr.delivered_by_id == admin_user.id and dr.delivered_at is not None


def test_approve_is_gated_to_accountant_admin(client, db_session, staff_user, admin_user,
                                              main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    # delivery_receipts is per_user + deny-by-default: grant the MODULE so the staff
    # user reaches the approve gate. Otherwise the before_request module gate bounces
    # them first and this test would pass for the wrong reason.
    perms = staff_user.get_book_permissions()
    perms['delivery_receipts'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch); db.session.commit()

    _login(client, staff_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)                        # staff may create a draft
    assert dr is not None
    resp = client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft'                                   # staff cannot approve
    assert b'approver' in resp.data.lower()
    assert so_line_open_qty(soi) == Decimal('10')                 # nothing committed


def test_billed_dr_cannot_be_cancelled(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    dr.status = 'billed'; db.session.commit()                     # sub-project #2 sets this
    resp = client.post(f'/delivery-receipts/{dr.id}/cancel',
                       data={'cancel_reason': 'Trying to cancel an already billed DR.'},
                       follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'billed'
    assert b'billed Delivery Receipt cannot be cancelled' in resp.data
