"""A delivery receipt can be made with no sales order (DR-NOSO, owner 17 Nov 2026: "right now DR must have an SO. but some
DR need no SO"; "A (my pick)": an explicit "No sales order" choice on the DR form, on every branch).

The customer and the lines (product, unit, quantity) are entered directly. Approving it has no ordered quantity to
cap. Billing it from the sales invoice prices each line from the product's default price and taxes it by the
customer's defaults -- editable on the invoice. The SO monitor never lists it (it has no SO line).
"""
import json
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.delivery_receipts.models import DeliveryReceipt
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure
from tests.integration.test_delivery_receipts_lifecycle import _branch, _login, dr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration]


@pytest.fixture
def stuff(db_session):
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    db.session.add(box); db.session.commit()
    cust = Customer(code='C9', name='Walk-in Hardware', is_active=True, default_vat_category=None)
    prod = Product(code='P9', name='Steel Drum', is_active=True, default_unit_price=Decimal('250.00'),
                   default_unit_of_measure_id=box.id)
    db.session.add_all([cust, prod]); db.session.commit()
    return cust, prod, box


def _create(client, cust_id, lines, **extra):
    data = {'sales_order_id': '0', 'customer_id': str(cust_id) if cust_id else '', 'delivery_date': '2026-11-17',
            'direct_lines': json.dumps(lines)}
    data.update(extra)
    return client.post('/delivery-receipts/create', data=data, follow_redirects=True)


def _last():
    return DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()


class TestCreating:

    def test_the_form_offers_no_sales_order(self, client, db_session, admin_user, main_branch, stuff):
        _login(client, admin_user); _branch(client, main_branch.id)
        html = client.get('/delivery-receipts/create').get_data(as_text=True)
        assert 'Deliver without a sales order' in html and 'name="direct_lines"' in html

    def test_a_dr_with_no_sales_order(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, box = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        _create(client, cust.id, [{'product_id': prod.id, 'uom_id': None, 'delivered_quantity': '3'}])
        dr = _last()
        assert dr is not None and dr.sales_order_id is None
        assert (dr.customer_id, dr.customer_name) == (cust.id, 'Walk-in Hardware')
        li = dr.line_items[0]
        assert (li.sales_order_item_id, li.product_id, li.delivered_quantity) == (None, prod.id, Decimal('3'))
        assert li.unit_of_measure.code == 'BOX', 'the product unit when none is chosen'

    def test_a_customer_is_required(self, client, db_session, admin_user, main_branch, stuff):
        _, prod, _ = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        resp = _create(client, None, [{'product_id': prod.id, 'delivered_quantity': '3'}])
        assert _last() is None and b'Choose the customer' in resp.data

    def test_a_line_is_required(self, client, db_session, admin_user, main_branch, stuff):
        cust, _, _ = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        resp = _create(client, cust.id, [])
        assert _last() is None and b'Add at least one delivered line' in resp.data


class TestItsLife:

    def test_edit_approve_and_deliver(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, box = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        _create(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '3'}])
        dr = _last()
        page = client.get(f'/delivery-receipts/{dr.id}/edit').get_data(as_text=True)
        assert 'Deliver without a sales order' in page
        client.post(f'/delivery-receipts/{dr.id}/edit', data={
            'sales_order_id': '0', 'customer_id': str(cust.id), 'delivery_date': '2026-11-17',
            'row_version': str(dr.row_version),
            'direct_lines': json.dumps([{'product_id': prod.id, 'uom_id': box.id, 'delivered_quantity': '5'}])},
            follow_redirects=True)
        db.session.expire_all()
        dr = db.session.get(DeliveryReceipt, dr.id)
        assert dr.line_items[0].delivered_quantity == Decimal('5')
        client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
        db.session.expire_all()
        assert db.session.get(DeliveryReceipt, dr.id).status == 'approved'
        page = client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)
        assert 'Steel Drum' in page

    def test_billing_prices_it_from_the_product(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, box = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        _create(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '2'}])
        dr = _last()
        dr.status = 'delivered'
        db.session.commit()
        payload = client.get(f'/sales-invoices/billable-drs?customer_id={cust.id}').get_json()
        line = next(d for d in payload['drs'] if d['id'] == dr.id)['lines'][0]
        assert line['unit_price'] == 250.0 and line['quantity'] == 2.0 and line['uom_display'] == 'BOX'
        assert line['sales_order_item_id'] is None
