"""B2 A in the browser: the DR form's Customer PO box follows the chosen order, and keeps what the user typed.

Owner, typed in the root 23 Nov 2026: "B2 A" -- "Against an order it starts as the order's PO and can be changed;
without one it's typed in." The server side (storing, page, prints, billing) is tests/integration/test_dr_customer_po.py;
this drives delivery_receipts.js on the DR smoke's own seeded server (tests/e2e/test_dr_smoke.py):
  Acme Customer Inc  one open order, SO-E2E-0001, no PO
  Gamma Stores       two open orders, SO-E2E-0101 (no PO) and SO-E2E-0102 (PO 4411)
"""
import pytest

from tests.e2e.test_dr_smoke import (CUSTOMER, ORDER, SO_QTY, _edit, _save, _saved, _way,  # noqa: F401
                                     dr_page, dr_server, pick, signed_in)

pytestmark = [pytest.mark.e2e, pytest.mark.delivery_receipts]

PO = '#customer_po_number'


def _po(page):
    return page.locator(PO).input_value()


def test_picking_an_order_fills_its_po_and_another_order_replaces_it(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    assert _po(page) == ''                                   # two orders: none chosen yet
    pick(page, ORDER, 'SO-E2E-0102')
    assert _po(page) == '4411'
    pick(page, ORDER, 'SO-E2E-0101')
    assert _po(page) == ''                                   # that order has none


def test_a_typed_po_is_kept(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    page.locator(PO).fill('HL-16674')
    pick(page, ORDER, 'SO-E2E-0101')
    assert _po(page) == 'HL-16674'
    _way(page, 'none').check()
    assert _po(page) == 'HL-16674'


def test_going_without_an_order_clears_the_orders_po_and_coming_back_fills_it(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    _way(page, 'none').check()
    assert _po(page) == ''
    _way(page, 'so').check()
    assert _po(page) == '4411'


def test_another_customer_clears_the_orders_po(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    pick(page, CUSTOMER, 'Acme Customer Inc')               # its one order has no PO
    assert _po(page) == ''


def test_a_changed_po_is_saved_and_kept_when_editing(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('1')
    page.locator(PO).fill('4411-B')
    _save(page)
    assert 'Customer PO: 4411-B' in _saved(page)
    _edit(page)
    assert _po(page) == '4411-B'                             # opening the edit does not put the order's back


def test_coming_from_an_order_opens_with_its_po(dr_page, dr_server):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    so_id = page.locator('#sales-order-id').input_value()
    page.goto(f'{dr_server}/delivery-receipts/create?so={so_id}')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert _po(page) == '4411'
    pick(page, ORDER, 'SO-E2E-0101')                        # still the order's, so it follows the order
    assert _po(page) == ''
