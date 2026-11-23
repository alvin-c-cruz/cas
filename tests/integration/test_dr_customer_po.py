"""B2 A: every delivery receipt carries its own Customer PO.

Owner, typed in the root 23 Nov 2026 13:3x: "B2 A". As put to him: "A Customer PO field on every DR. Against an order it
starts as the order's PO and can be changed; without one it's typed in. The DR page, both DR prints and the invoice's DR
billing then use the DR's own PO." Philgen SO-DR trial, 22 Nov 2026: DR 0264 (Hi-Las, no sales order) carried PO 16674
and had nowhere to keep it. Work order: 2026-11-22-dr-no-customer-po-field.md.

Migration drpo_0001 adds delivery_receipts.customer_po_number and fills it for existing DRs from their order's PO
(tests/integration/test_drpo_migration.py), so a DR printed before keeps printing the same PO.
"""
import json
import re

import pytest

from app import db
from app.delivery_receipts.models import DeliveryReceipt
from tests.integration.test_delivery_receipts_lifecycle import _branch, _confirmed_so, _login, dr_enabled  # noqa: F401
from tests.integration.test_dr_without_sales_order import _create as _create_without_so, _last, stuff  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture
def so(db_session, main_branch):
    order = _confirmed_so(db_session, main_branch.id)
    order.customer_po_number = 'PO-777'
    db.session.commit()
    return order


def _open(client, admin_user, main_branch):
    _login(client, admin_user)
    _branch(client, main_branch.id)


def _create_against(client, order, **extra):
    data = {'sales_order_id': order.id, 'dr_source': 'so', 'delivery_date': '2026-11-23',
            'lines': json.dumps([{'sales_order_item_id': order.line_items[0].id, 'delivered_quantity': '4'}])}
    data.update(extra)
    client.post('/delivery-receipts/create', data=data, follow_redirects=True)
    return _last()


def _po_box(html):
    m = re.search(r'<input[^>]*id="customer_po_number"[^>]*>', html)
    assert m, 'the form has no Customer PO box'
    value = re.search(r'value="([^"]*)"', m.group(0))
    return value.group(1) if value else ''


# --- Stored ------------------------------------------------------------------------------------------------------------

class TestStored:

    def test_against_an_order_the_po_as_sent(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777')
        assert dr.sales_order_id == so.id and dr.customer_po_number == 'PO-777'

    def test_against_an_order_a_changed_po(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='  PO-777-B  ')
        assert dr.customer_po_number == 'PO-777-B'
        assert so.customer_po_number == 'PO-777', "the order's own PO is not touched"

    def test_against_an_order_a_cleared_po_stays_empty(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='')
        assert dr.customer_po_number is None

    def test_a_form_without_the_box_keeps_the_orders_po(self, client, db_session, admin_user, main_branch, so):
        """A page opened before the deploy posts no Customer PO at all: the DR still gets its order's PO."""
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so)
        assert dr.customer_po_number == 'PO-777'

    def test_without_an_order_the_typed_po(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, _ = stuff
        _open(client, admin_user, main_branch)
        _create_without_so(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '3'}],
                           dr_source='none', customer_po_number='16674')
        dr = _last()
        assert dr.sales_order_id is None and dr.customer_po_number == '16674'

    def test_too_long_a_po_is_refused(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        assert _create_against(client, so, customer_po_number='X' * 101) is None


class TestEditing:

    def test_a_draft_takes_a_new_po(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777')
        assert _po_box(client.get(f'/delivery-receipts/{dr.id}/edit').get_data(as_text=True)) == 'PO-777'
        client.post(f'/delivery-receipts/{dr.id}/edit', data={
            'delivery_date': '2026-11-23', 'row_version': str(dr.row_version), 'customer_po_number': 'PO-778',
            'lines': json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])},
            follow_redirects=True)
        db.session.expire_all()
        assert db.session.get(DeliveryReceipt, dr.id).customer_po_number == 'PO-778'

    def test_an_edit_without_the_box_keeps_the_po(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777-B')
        client.post(f'/delivery-receipts/{dr.id}/edit', data={
            'delivery_date': '2026-11-23', 'row_version': str(dr.row_version),
            'lines': json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])},
            follow_redirects=True)
        db.session.expire_all()
        assert db.session.get(DeliveryReceipt, dr.id).customer_po_number == 'PO-777-B'


# --- The form ----------------------------------------------------------------------------------------------------------

class TestTheForm:

    def test_a_new_dr_has_an_empty_box(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        html = client.get('/delivery-receipts/create').get_data(as_text=True)
        assert _po_box(html) == ''
        assert re.search(r'<label[^>]*for="customer_po_number"[^>]*>\s*Customer PO\s*</label>', html)

    def test_coming_from_an_order_starts_with_its_po(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        assert _po_box(client.get(f'/delivery-receipts/create?so={so.id}').get_data(as_text=True)) == 'PO-777'

    def test_each_order_carries_its_po_for_the_page(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        html = client.get('/delivery-receipts/create').get_data(as_text=True)
        orders = json.loads(re.search(r'<script type="application/json" id="dr-orders-data">(.*?)</script>',
                                      html, re.S).group(1))
        assert [(o['id'], o['po']) for o in orders] == [(so.id, 'PO-777')]


# --- Where it shows ----------------------------------------------------------------------------------------------------

class TestWhereItShows:

    def test_the_dr_page(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777-B')
        html = client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)
        assert re.search(r'<strong>Customer PO:</strong>\s*PO-777-B', html)

    def test_the_dr_page_without_a_po_says_nothing(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='')
        assert 'Customer PO:' not in client.get(f'/delivery-receipts/{dr.id}').get_data(as_text=True)

    def test_the_standard_print(self, client, db_session, admin_user, main_branch, so):
        from app.settings import AppSettings
        AppSettings.set_setting('dr_print_form', 'current', 'admin')
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777-B')
        html = client.get(f'/delivery-receipts/{dr.id}/print').get_data(as_text=True)
        assert re.search(r'<td class="label">PO No\.</td><td>PO-777-B</td>', html)

    def test_the_preprinted_print_takes_the_drs_own_po(self, client, db_session, admin_user, main_branch, so):
        from app.settings import AppSettings
        AppSettings.set_setting('dr_print_form', 'preprinted', 'admin')
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777-B')
        html = client.get(f'/delivery-receipts/{dr.id}/print').get_data(as_text=True)
        field = re.search(r'<div class="pp-el[^"]*" data-el="customer_po"[^>]*>(.*?)</div>', html, re.S)
        assert field and field.group(1).strip() == 'PO-777-B', field and field.group(0)

    def test_the_preprinted_print_without_an_order(self, client, db_session, admin_user, main_branch, stuff):
        from app.settings import AppSettings
        AppSettings.set_setting('dr_print_form', 'preprinted', 'admin')
        cust, prod, _ = stuff
        _open(client, admin_user, main_branch)
        _create_without_so(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '3'}],
                           dr_source='none', customer_po_number='16674')
        html = client.get(f'/delivery-receipts/{_last().id}/print').get_data(as_text=True)
        field = re.search(r'<div class="pp-el[^"]*" data-el="customer_po"[^>]*>(.*?)</div>', html, re.S)
        assert field and field.group(1).strip() == '16674', field and field.group(0)


class TestTheInvoicesDrBilling:

    def _billable(self, client, customer_id, dr):
        dr.status = 'delivered'
        db.session.commit()
        payload = client.get(f'/sales-invoices/billable-drs?customer_id={customer_id}').get_json()
        return next(d for d in payload['drs'] if d['id'] == dr.id)

    def test_a_dr_against_an_order_bills_with_its_own_po(self, client, db_session, admin_user, main_branch, so):
        _open(client, admin_user, main_branch)
        dr = _create_against(client, so, customer_po_number='PO-777-B')
        assert self._billable(client, so.customer_id, dr)['customer_po_number'] == 'PO-777-B'

    def test_a_dr_without_an_order_bills_with_its_po(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, _ = stuff
        _open(client, admin_user, main_branch)
        _create_without_so(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '3'}],
                           dr_source='none', customer_po_number='16674')
        assert self._billable(client, cust.id, _last())['customer_po_number'] == '16674'
