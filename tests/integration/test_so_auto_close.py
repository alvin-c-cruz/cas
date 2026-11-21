"""SO-CLOSED A (owner, 22 Nov 2026): a confirmed Sales Order closes itself once every line is
fully delivered or closed short, and goes back to Confirmed when a cancelled Delivery Receipt
opens quantity again. Work order: app-docs/bug-reports/2026-08-18-open-bug-triage.md
(BUG-SO-CLOSED-STATUS-DECLARED-BUT-UNREACHABLE)."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, so_line_open_qty

from tests.integration._so_helpers import sales_orders_module_enabled  # noqa: F401 (autouse)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


@pytest.fixture
def logged_in(client, admin_user, main_branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(admin_user.id); s['_fresh'] = True
        s['selected_branch_id'] = main_branch.id
    return client


def _confirmed_so(branch_id, quantities, so_number='SO-AC-1'):
    c = Customer(code='C-' + so_number, name='Acme ' + so_number, is_active=True)
    p = Product(code='W-' + so_number, name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number=so_number, order_date=date(2026, 11, 2), customer_id=c.id,
                    customer_name=c.name, branch_id=branch_id, status='confirmed')
    for n, q in enumerate(quantities, start=1):
        so.line_items.append(SalesOrderItem(line_number=n, product_id=p.id, quantity=Decimal(q),
                                            unit_price=Decimal('100'),
                                            amount=Decimal(q) * Decimal('100')))
    db.session.add(so); db.session.commit()
    return so


def _approved_dr(client, so, deliveries):
    """deliveries: [(sales_order_item, qty)]. Created and approved through the routes."""
    lines = json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': str(q)}
                        for soi, q in deliveries])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-11-05', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()
    resp = client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db.session.refresh(dr)
    assert dr.status == 'approved'
    return dr, resp


def _status_audits(so):
    return [a for a in AuditLog.query.filter_by(module='sales_orders', record_id=so.id).all()
            if a.new_values and '"status"' in a.new_values]


def test_partial_delivery_leaves_the_order_confirmed(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10', '5'])
    _approved_dr(logged_in, so, [(so.line_items[0], 10), (so.line_items[1], 2)])
    db.session.refresh(so)
    assert so.status == 'confirmed'


def test_order_closes_when_the_last_line_is_fully_delivered(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10', '5'])
    _approved_dr(logged_in, so, [(so.line_items[0], 10)])
    db.session.refresh(so)
    assert so.status == 'confirmed'

    _, resp = _approved_dr(logged_in, so, [(so.line_items[1], 5)])
    db.session.refresh(so)
    assert so.status == 'closed'
    assert b'is now Closed' in resp.data
    audits = _status_audits(so)
    assert len(audits) == 1
    assert json.loads(audits[0].old_values)['status'] == 'confirmed'
    assert json.loads(audits[0].new_values)['status'] == 'closed'


def test_cancelling_a_dr_reopens_a_closed_order(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10'])
    dr, _ = _approved_dr(logged_in, so, [(so.line_items[0], 10)])
    db.session.refresh(so)
    assert so.status == 'closed'

    resp = logged_in.post(f'/delivery-receipts/{dr.id}/cancel',
                          data={'cancel_reason': 'Customer refused the delivery at the gate.'},
                          follow_redirects=True)
    db.session.refresh(so); db.session.refresh(dr)
    assert dr.status == 'cancelled'
    assert so.status == 'confirmed'
    assert so_line_open_qty(so.line_items[0]) == Decimal('10')
    assert b'is back to Confirmed' in resp.data
    statuses = [json.loads(a.new_values)['status'] for a in _status_audits(so)]
    assert statuses == ['closed', 'confirmed']


def test_cancelling_a_draft_dr_changes_nothing(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10'])
    _approved_dr(logged_in, so, [(so.line_items[0], 4)])
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '6'}])
    logged_in.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-11-06', 'lines': lines},
        follow_redirects=True)
    draft = DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()
    logged_in.post(f'/delivery-receipts/{draft.id}/cancel',
                   data={'cancel_reason': 'Typed the wrong quantity on this one.'},
                   follow_redirects=True)
    db.session.refresh(so)
    assert so.status == 'confirmed'
    assert _status_audits(so) == []


def test_closing_the_last_open_line_short_closes_the_order(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10', '5'])
    _approved_dr(logged_in, so, [(so.line_items[0], 10), (so.line_items[1], 2)])
    resp = logged_in.post(f'/sales-orders/{so.id}/lines/{so.line_items[1].id}/close',
                          data={'closed_reason': 'Customer will not take the balance.'},
                          follow_redirects=True)
    db.session.refresh(so)
    assert so.line_items[1].line_status == 'closed'
    assert so.status == 'closed'
    assert b'is now Closed' in resp.data


def test_a_line_closed_short_with_nothing_delivered_counts_as_done(logged_in, main_branch):
    so = _confirmed_so(main_branch.id, ['10', '5'])
    logged_in.post(f'/sales-orders/{so.id}/lines/{so.line_items[1].id}/close',
                   data={'closed_reason': 'Item discontinued by the customer.'},
                   follow_redirects=True)
    db.session.refresh(so)
    assert so.status == 'confirmed'          # line 1 still open
    _approved_dr(logged_in, so, [(so.line_items[0], 10)])
    db.session.refresh(so)
    assert so.status == 'closed'


def test_closed_filter_lists_an_auto_closed_order(logged_in, main_branch):
    done = _confirmed_so(main_branch.id, ['3'], so_number='SO-AC-DONE')
    still_open = _confirmed_so(main_branch.id, ['3'], so_number='SO-AC-OPEN')
    _approved_dr(logged_in, done, [(done.line_items[0], 3)])
    resp = logged_in.get('/sales-orders?status=closed')
    assert resp.status_code == 200
    # Scoped to each order's row link: the customer filter lists every customer, open or not.
    assert f'href="/sales-orders/{done.id}"'.encode() in resp.data
    assert f'href="/sales-orders/{still_open.id}"'.encode() not in resp.data


def test_amending_a_line_down_to_what_was_delivered_closes_the_order(logged_in, db_session):
    """Amend drives the real routes: create, confirm (Rev 0), deliver 6 of 10, amend to 6."""
    from tests.integration._so_helpers import _customer, _product, _enable_products
    _enable_products(db_session)
    customer, product = _customer(db_session), _product(db_session)
    line = {'line_number': 1, 'product_id': product.id, 'quantity': '10',
            'unit_price': '4.20', 'amount': '42.00'}
    logged_in.post('/sales-orders/create', data={
        'so_number': '2026110001', 'order_date': '2026-11-02', 'customer_id': str(customer.id),
        'payment_terms': 'Net 30', 'notes': '', 'line_items': json.dumps([line])},
        follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='2026110001').one()
    logged_in.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db.session.refresh(so)
    assert so.status == 'confirmed'
    _approved_dr(logged_in, so, [(so.line_items[0], 6)])
    db.session.refresh(so)
    assert so.status == 'confirmed'

    line.update(so_item_id=so.line_items[0].id, quantity='6', amount='25.20')
    resp = logged_in.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026110001', 'order_date': '2026-11-02', 'customer_id': str(customer.id),
        'payment_terms': 'Net 30', 'notes': '', 'line_items': json.dumps([line]),
        'amend_reason': 'Customer cut the order to what was delivered',
        'authorizing_po_number': 'PO-CUT-6', 'row_version': str(so.row_version)},
        follow_redirects=True)
    db.session.refresh(so)
    assert so.line_items[0].quantity == Decimal('6')
    assert so.status == 'closed'
    assert b'is now Closed' in resp.data
