"""D12a (Philgen SO-DR trial, 22 Nov 2026): a delivery receipt without a sales order showed its lines with a blank UOM
and a blank ORDERED on its page (DR 0264: DELIVERED 100, nothing else).

The line's unit came only from the sales-order line, which such a line does not have. It now comes from the line's own
unit, else its product's default unit -- the unit it was delivered in (DeliveryReceiptItem.unit_of_measure). ORDERED
reads "—": there is no order. The DR print (current form) takes the unit the same way.
"""
import json
import re
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.delivery_receipts.models import DeliveryReceipt
from app.products.models import Product
from app.units_of_measure.models import UnitOfMeasure
from tests.integration.test_delivery_receipts_lifecycle import _branch, _login, dr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture
def stuff(db_session):
    box = UnitOfMeasure(code='BOX', name='Box', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    db.session.add_all([box, kg]); db.session.commit()
    cust = Customer(code='C9', name='Walk-in Hardware', is_active=True)
    drum = Product(code=None, name='Steel Drum', is_active=True, default_unit_of_measure_id=box.id)
    db.session.add_all([cust, drum]); db.session.commit()
    return cust, drum, box, kg


def _dr_without_order(client, cust, lines):
    client.post('/delivery-receipts/create', data={
        'sales_order_id': '0', 'dr_source': 'none', 'customer_id': str(cust.id), 'delivery_date': '2026-11-22',
        'direct_lines': json.dumps(lines)}, follow_redirects=True)
    return DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()


def _row(html, product):
    """The cells of the line row that names the product."""
    for row in re.findall(r'<tr>(.*?)</tr>', html, re.S):
        if product in row:
            return [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
    raise AssertionError(f'no row for {product}')


def test_the_line_shows_the_unit_it_was_delivered_in(client, db_session, admin_user, main_branch, stuff):
    cust, drum, box, kg = stuff
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _dr_without_order(client, cust, [{'product_id': drum.id, 'uom_id': kg.id, 'delivered_quantity': '100'}])
    assert dr.line_items[0].to_dict()['uom'] == 'KG'
    page = client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)
    assert _row(page, 'Steel Drum') == ['1', 'Steel Drum', 'KG', '—', '100']


def test_without_a_unit_of_its_own_the_line_shows_the_products(client, db_session, admin_user, main_branch, stuff):
    cust, drum, box, kg = stuff
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _dr_without_order(client, cust, [{'product_id': drum.id, 'uom_id': None, 'delivered_quantity': '3'}])
    page = client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)
    assert _row(page, 'Steel Drum')[2] == 'BOX'


def test_the_print_shows_the_unit_too(client, db_session, admin_user, main_branch, stuff):
    from app.settings import AppSettings
    cust, drum, box, kg = stuff
    AppSettings.set_setting('dr_print_form', 'current'); db_session.commit()
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _dr_without_order(client, cust, [{'product_id': drum.id, 'uom_id': kg.id, 'delivered_quantity': '100'}])
    page = client.get(f'/delivery-receipts/{dr.id}/print').get_data(as_text=True)
    assert _row(page, 'Steel Drum') == ['1', 'Steel Drum', 'KG', '100']


def test_a_line_of_an_order_is_as_before(client, db_session, admin_user, main_branch):
    """CONTROL: against an order, the unit and the ordered quantity come from the order line."""
    from datetime import date
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    cust = Customer(code='C1', name='Acme', is_active=True)
    widget = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([pc, cust, widget]); db.session.commit()
    so = SalesOrder(so_number='SO-U-1', order_date=date(2026, 11, 22), customer_id=cust.id, customer_name='Acme',
                    branch_id=main_branch.id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=widget.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000'), unit_of_measure_id=pc.id))
    db.session.add(so); db.session.commit()
    _login(client, admin_user); _branch(client, main_branch.id)
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'dr_source': 'so', 'customer_id': cust.id, 'delivery_date': '2026-11-22',
        'lines': json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).one()
    page = client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)
    assert _row(page, 'Widget') == ['1', 'Widget', 'PC', '10', '4']
