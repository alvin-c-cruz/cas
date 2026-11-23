"""BUG-10 A: the Delivery Receipt form follows the Sales Invoice form.

Owner, in-app report #10 (22 Nov 2026): "The DR should follow design conventions of SI. DR can be made with or without
an SO. And also the css design should be similar." Then, in the root session: "DR should also follow the design concept
of SI." and "A".

A = the SI's look and order of steps. The customer comes first; then one plain choice, "Deliver against a sales order"
(one of that customer's confirmed orders with open lines) or "Deliver without a sales order"; one lines table. What a
delivery receipt holds does not change: one sales order or none.

These tests read what the server renders and what it accepts. What the page does in a browser is in
tests/e2e/test_dr_smoke.py. Work order: app-docs/bug-reports/2026-11-22-dr-form-follows-si-conventions.md.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.delivery_receipts.models import DeliveryReceipt
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from tests.integration.test_delivery_receipts_lifecycle import _branch, _login, dr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]

CREATE = '/delivery-receipts/create'


def _order(number, customer, product, branch_id, on=date(2026, 7, 9), status='confirmed', po=None, qty='10'):
    so = SalesOrder(so_number=number, order_date=on, customer_id=customer.id, customer_name=customer.name,
                    branch_id=branch_id, status=status, customer_po_number=po)
    so.line_items.append(SalesOrderItem(line_number=1, product_id=product.id, quantity=Decimal(qty),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    return so


@pytest.fixture
def books(db_session, main_branch):
    """Acme has one open order; Borromeo has none; Widget is the product."""
    acme = Customer(code='C1', name='Acme', is_active=True)
    borromeo = Customer(code='C2', name='Borromeo Trading', is_active=True)
    widget = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([acme, borromeo, widget]); db.session.commit()
    so = _order('SO-C-1', acme, widget, main_branch.id)
    return acme, borromeo, widget, so


def _data(html, element_id):
    """The JSON the page hands its script in <script type="application/json" id="...">."""
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % re.escape(element_id), html, re.S)
    assert m, f'no JSON block #{element_id} on the page'
    return json.loads(m.group(1))


def _page(client, url=CREATE):
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _post(client, url=CREATE, **data):
    data.setdefault('delivery_date', '2026-07-09')
    return client.post(url, data=data, follow_redirects=True)


def _so_lines(soi, qty):
    return json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': str(qty)}])


def _free_lines(product, qty, uom_id=None):
    return json.dumps([{'product_id': product.id, 'uom_id': uom_id, 'delivered_quantity': str(qty)}])


# --- the create page -------------------------------------------------------------------------------------------------

class TestTheCreatePage:

    def test_it_is_built_from_the_sales_invoice_forms_parts(self, client, admin_user, main_branch, books):
        _login(client, admin_user); _branch(client, main_branch.id)
        html = _page(client)
        for part in ("transactions.css", "accounts_payable_form.css", "choices.min.css", "choices.min.js",
                     "search-select.js", "js/delivery_receipts.js?v=5",
                     'class="card card--lines page-sales-invoice page-delivery-receipt"', 'class="form-main-grid',
                     'id="customerCard"', 'id="customerCardLabel"', 'id="lineItemsLocked"', 'id="lineItemsSection"'):
            assert part in html, part
        assert 'Select Customer' in html
        assert 'Select a customer above to enter the delivery' in html
        # the page's name is in the top bar, as on the SI form: no second title and no "Back to list" on the page
        assert 'class="page-header"' not in html and 'Back to list' not in html
        assert html.count('Enter Delivery Receipt') == 2          # the browser tab and the top bar

    def test_the_customer_comes_first_and_both_ways_are_offered(self, client, admin_user, main_branch, books):
        acme, borromeo, _, _ = books
        _login(client, admin_user); _branch(client, main_branch.id)
        html = _page(client)
        customer = re.search(r'<select[^>]*id="dr-customer"[^>]*>(.*?)</select>', html, re.S)
        assert customer and 'name="customer_id"' in customer.group(0)
        assert re.findall(r'<option[^>]*value="(\d*)"[^>]*>\s*([^<]*?)\s*</option>', customer.group(1)) == [
            ('', '-- Select Customer --'), (str(acme.id), 'C1 - Acme'), (str(borromeo.id), 'C2 - Borromeo Trading')]
        assert html.index('id="dr-customer"') < html.index('name="dr_source"')
        assert re.search(r'<input[^>]*type="radio"[^>]*name="dr_source"[^>]*value="so"', html)
        assert re.search(r'<input[^>]*type="radio"[^>]*name="dr_source"[^>]*value="none"', html)
        assert 'Deliver against a sales order' in html and 'Deliver without a sales order' in html
        # one of each posted field: a second copy would post an empty value first (BUG-DR-DUP-LINES)
        for name in ('sales_order_id', 'lines', 'direct_lines', 'customer_id', 'row_version'):
            assert html.count(f'name="{name}"') == 1, name
        # one lines table, for a delivery with an order and for one without
        assert html.count('<table') == 1 and 'id="lineItemsTable"' in html

    def test_the_orders_are_handed_to_the_page_by_customer(self, client, admin_user, main_branch, books):
        acme, borromeo, widget, so = books
        second = _order('SO-C-2', acme, widget, main_branch.id, on=date(2026, 7, 10), po='4411')
        _order('SO-C-3', acme, widget, main_branch.id, status='draft')            # not confirmed: not offered
        _login(client, admin_user); _branch(client, main_branch.id)
        assert _data(_page(client), 'dr-orders-data') == [
            {'id': second.id, 'customer_id': acme.id, 'label': 'SO-C-2 · Jul 10, 2026 · PO 4411', 'po': '4411'},
            {'id': so.id, 'customer_id': acme.id, 'label': 'SO-C-1 · Jul 09, 2026', 'po': ''}]

    def test_a_customer_made_inactive_is_still_offered_while_an_order_of_theirs_is_open(self, client, admin_user,
                                                                                        main_branch, books):
        acme, borromeo, _, _ = books
        acme.is_active = False
        borromeo.is_active = False
        db.session.commit()
        _login(client, admin_user); _branch(client, main_branch.id)
        customer = re.search(r'<select[^>]*id="dr-customer"[^>]*>(.*?)</select>', _page(client), re.S).group(1)
        assert 'Acme' in customer and 'Borromeo Trading' not in customer

    def test_a_name_cannot_break_out_of_the_page(self, client, admin_user, main_branch, books):
        _, _, widget, _ = books
        nasty = '</script><script>alert(1)</script>'
        villain = Customer(code='C9', name=f'Ace {nasty}', is_active=True)
        gadget = Product(code='G', name=f'Gadget {nasty}', is_active=True)
        db.session.add_all([villain, gadget]); db.session.commit()
        so = _order('SO-C-9', villain, gadget, main_branch.id, po=nasty)
        _login(client, admin_user); _branch(client, main_branch.id)
        for url in (CREATE, f'{CREATE}?so={so.id}'):
            html = _page(client, url)
            assert '<script>alert(1)' not in html, url
            assert _data(html, 'dr-orders-data')[0]['label'].endswith(f'PO {nasty}')      # carried, as text

    def test_nothing_is_chosen_until_the_user_chooses(self, client, admin_user, main_branch, books):
        _login(client, admin_user); _branch(client, main_branch.id)
        assert _data(_page(client), 'dr-selected-data') == {
            'customer_id': None, 'source': '', 'sales_order_id': None, 'locked': False}

    def test_coming_from_a_sales_order_starts_on_its_customer_and_that_order(self, client, admin_user, main_branch,
                                                                             books):
        acme, _, _, so = books
        _login(client, admin_user); _branch(client, main_branch.id)
        assert _data(_page(client, f'{CREATE}?so={so.id}'), 'dr-selected-data') == {
            'customer_id': acme.id, 'source': 'so', 'sales_order_id': so.id, 'locked': False}


# --- saving ------------------------------------------------------------------------------------------------------------

class TestSaving:

    def test_against_a_sales_order_and_without_one_both_save(self, client, admin_user, main_branch, books):
        acme, borromeo, widget, so = books
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id, dr_number='70001',
              lines=_so_lines(so.line_items[0], 4), direct_lines='[]')
        _post(client, customer_id=borromeo.id, dr_source='none', sales_order_id='0', dr_number='70002',
              lines='[]', direct_lines=_free_lines(widget, 3))
        with_order = DeliveryReceipt.query.filter_by(dr_number='70001').one()
        without = DeliveryReceipt.query.filter_by(dr_number='70002').one()
        assert (with_order.sales_order_id, with_order.customer_id) == (so.id, acme.id)
        assert [(li.sales_order_item_id, li.delivered_quantity) for li in with_order.line_items] == [
            (so.line_items[0].id, Decimal('4'))]
        assert (without.sales_order_id, without.customer_id) == (None, borromeo.id)
        assert [(li.product_id, li.delivered_quantity) for li in without.line_items] == [(widget.id, Decimal('3'))]

    def test_against_a_sales_order_without_naming_one_is_refused(self, client, admin_user, main_branch, books):
        """It must not slip into "without a sales order" because the order field came empty."""
        acme, _, widget, _ = books
        _login(client, admin_user); _branch(client, main_branch.id)
        resp = _post(client, customer_id=acme.id, dr_source='so', sales_order_id='',
                     lines='[]', direct_lines=_free_lines(widget, 3))
        assert DeliveryReceipt.query.count() == 0
        assert 'Select the sales order to deliver against' in resp.get_data(as_text=True)

    def test_an_order_of_another_customer_is_refused(self, client, admin_user, main_branch, books):
        _, borromeo, _, so = books
        _login(client, admin_user); _branch(client, main_branch.id)
        resp = _post(client, customer_id=borromeo.id, dr_source='so', sales_order_id=so.id,
                     lines=_so_lines(so.line_items[0], 4))
        assert DeliveryReceipt.query.count() == 0
        html = resp.get_data(as_text=True)
        assert 'That sales order belongs to another customer' in html
        # the page comes back on the customer, with no order: Acme's order is not Borromeo's to pick
        assert _data(html, 'dr-selected-data') == {
            'customer_id': borromeo.id, 'source': 'so', 'sales_order_id': None, 'locked': False}

    def test_a_customer_the_page_does_not_offer_is_not_given_back_as_chosen(self, client, admin_user, main_branch,
                                                                            books):
        _, borromeo, widget, _ = books
        borromeo.is_active = False                                 # inactive, and no open order: not offered
        db.session.commit()
        _login(client, admin_user); _branch(client, main_branch.id)
        html = _post(client, customer_id=borromeo.id, dr_source='none', sales_order_id='0',
                     direct_lines=_free_lines(widget, 3)).get_data(as_text=True)
        assert DeliveryReceipt.query.count() == 0 and 'Choose the customer' in html
        assert _data(html, 'dr-selected-data') == {
            'customer_id': None, 'source': '', 'sales_order_id': None, 'locked': False}

    def test_a_line_of_another_order_is_refused(self, client, admin_user, main_branch, books):
        acme, _, widget, so = books
        other = _order('SO-C-2', acme, widget, main_branch.id)
        _login(client, admin_user); _branch(client, main_branch.id)
        resp = _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id,
                     lines=_so_lines(other.line_items[0], 4))
        assert DeliveryReceipt.query.count() == 0
        assert 'A line does not belong to this sales order' in resp.get_data(as_text=True)

    def test_a_refused_save_gives_back_the_customer_the_order_and_the_quantities(self, client, admin_user,
                                                                                 main_branch, books):
        acme, _, _, so = books
        soi = so.line_items[0]
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id, dr_number='25069',
              lines=_so_lines(soi, 2))
        html = _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id, dr_number='25069',
                     lines=_so_lines(soi, 3)).get_data(as_text=True)
        assert 'already exists' in html and DeliveryReceipt.query.count() == 1
        assert _data(html, 'dr-selected-data') == {
            'customer_id': acme.id, 'source': 'so', 'sales_order_id': so.id, 'locked': False}
        assert _data(html, 'dr-existing-data') == {str(soi.id): 3.0}

    def test_a_refused_save_without_an_order_gives_back_its_lines(self, client, admin_user, main_branch, books):
        acme, borromeo, widget, so = books
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id, dr_number='25069',
              lines=_so_lines(so.line_items[0], 2))
        html = _post(client, customer_id=borromeo.id, dr_source='none', sales_order_id='0', dr_number='25069',
                     lines='[]', direct_lines=_free_lines(widget, 3)).get_data(as_text=True)
        assert 'already exists' in html and DeliveryReceipt.query.count() == 1
        assert _data(html, 'dr-selected-data') == {
            'customer_id': borromeo.id, 'source': 'none', 'sales_order_id': None, 'locked': False}
        assert _data(html, 'dr-noso-data')['existing'] == [
            {'product_id': widget.id, 'uom_id': None, 'delivered_quantity': 3.0}]


# --- the edit page -----------------------------------------------------------------------------------------------------

class TestTheEditPage:

    def test_a_delivery_against_an_order_keeps_its_customer_and_its_order(self, client, admin_user, main_branch,
                                                                          books):
        acme, _, widget, so = books
        _order('SO-C-2', acme, widget, main_branch.id)                # another open order of the same customer
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=acme.id, dr_source='so', sales_order_id=so.id, lines=_so_lines(so.line_items[0], 4))
        dr = DeliveryReceipt.query.one()
        html = _page(client, f'/delivery-receipts/{dr.id}/edit')
        assert _data(html, 'dr-selected-data') == {
            'customer_id': acme.id, 'source': 'so', 'sales_order_id': so.id, 'locked': True}
        # only its own order: a draft's order cannot be swapped for another
        assert _data(html, 'dr-orders-data') == [
            {'id': so.id, 'customer_id': acme.id, 'label': 'SO-C-1 · Jul 09, 2026', 'po': ''}]
        assert _data(html, 'dr-existing-data') == {str(so.line_items[0].id): 4.0}
        assert re.search(r'<select[^>]*id="dr-customer"[^>]*\bdisabled\b', html)
        assert '&#10003; C1 - Acme' in html              # "CODE - Name", as the SI form reads its customers
        assert html.count(f'Edit Delivery Receipt {dr.dr_number}') == 2

    def test_one_without_an_order_opens_as_without(self, client, admin_user, main_branch, books):
        _, borromeo, widget, _ = books
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=borromeo.id, dr_source='none', sales_order_id='0', direct_lines=_free_lines(widget, 3))
        dr = DeliveryReceipt.query.one()
        html = _page(client, f'/delivery-receipts/{dr.id}/edit')
        assert _data(html, 'dr-selected-data') == {
            'customer_id': borromeo.id, 'source': 'none', 'sales_order_id': None, 'locked': True}
        assert _data(html, 'dr-orders-data') == []
        assert _data(html, 'dr-noso-data')['existing'] == [
            {'product_id': widget.id, 'uom_id': None, 'delivered_quantity': 3.0}]

    def test_a_refused_edit_gives_back_the_lines_typed_for_a_delivery_without_an_order(self, client, admin_user,
                                                                                       main_branch, books):
        _, borromeo, widget, _ = books
        _login(client, admin_user); _branch(client, main_branch.id)
        _post(client, customer_id=borromeo.id, dr_source='none', sales_order_id='0', direct_lines=_free_lines(widget, 3))
        dr = DeliveryReceipt.query.one()
        html = _post(client, f'/delivery-receipts/{dr.id}/edit', customer_id=borromeo.id, sales_order_id='0',
                     row_version=str(dr.row_version + 7),                 # someone else saved it meanwhile
                     direct_lines=_free_lines(widget, 8)).get_data(as_text=True)
        db.session.expire_all()
        assert db.session.get(DeliveryReceipt, dr.id).line_items[0].delivered_quantity == Decimal('3')
        assert _data(html, 'dr-noso-data')['existing'] == [
            {'product_id': widget.id, 'uom_id': None, 'delivered_quantity': 8.0}]
