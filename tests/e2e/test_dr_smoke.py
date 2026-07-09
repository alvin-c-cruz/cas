"""
Playwright e2e smoke tests for the Delivery Receipt create form — the open-qty grid
JS (delivery_receipts.js) that renders a confirmed SO's lines and serializes the
delivered quantities into the hidden `lines` field. pytest's HTML-only tests never
execute this JS, so this is its only browser coverage.

Runs against `sales_e2e_server`, which seeds a confirmed Sales Order (SO-E2E-0001:
one product line, qty 10, fully open).

Run: python -m playwright install chromium   (once)
     pytest -m delivery_receipts
"""
import json
import re

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.delivery_receipts]

DR_CREATE = '/delivery-receipts/create'


def _grid_rows(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('#dr-lines tbody tr')].map(tr =>
            [...tr.querySelectorAll('td')].map(td => {
                const inp = td.querySelector('input');
                return inp ? inp.value : td.textContent.trim();
            }))"""
    )


def test_so_select_renders_open_lines(logged_in_sales_page, sales_e2e_server):
    """Choosing the confirmed SO renders its open lines into the grid."""
    page = logged_in_sales_page
    page.goto(sales_e2e_server + DR_CREATE)
    page.wait_for_selector('#so-select')

    # Select the seeded confirmed SO (triggers the JS render).
    page.locator('#so-select').select_option(label='SO-E2E-0001: Acme Customer Inc')
    page.wait_for_selector('#dr-lines tbody tr')

    rows = _grid_rows(page)
    assert len(rows) == 1, rows
    product, uom, ordered, delivered, open_qty, deliver_now = rows[0]
    assert 'P001' in product, product
    assert uom == 'PC', uom
    assert float(ordered) == 10.0, ordered
    assert float(delivered) == 0.0, delivered
    assert float(open_qty) == 10.0, open_qty
    # No Delivery Receipt exists yet -> the "no lines" hint is hidden.
    assert page.locator('#dr-no-lines').is_hidden()


def test_deliver_qty_serializes_into_hidden_field(logged_in_sales_page, sales_e2e_server):
    """Typing a delivered quantity serializes {sales_order_item_id, delivered_quantity}
    into the hidden `lines` field for POST."""
    page = logged_in_sales_page
    page.goto(sales_e2e_server + DR_CREATE)
    page.wait_for_selector('#so-select')
    page.locator('#so-select').select_option(label='SO-E2E-0001: Acme Customer Inc')
    page.wait_for_selector('#dr-lines tbody tr')

    qty = page.locator('#dr-lines tbody tr .qty-input').first
    qty.fill('4')
    qty.dispatch_event('input')

    serialized = json.loads(page.locator('#lines-json').input_value())
    assert len(serialized) == 1, serialized
    assert serialized[0]['delivered_quantity'] in ('4', '4.0'), serialized
    assert isinstance(serialized[0]['sales_order_item_id'], int), serialized


def test_dr_round_trip_submit(logged_in_sales_page, sales_e2e_server):
    """A delivery of part of the open qty submits, persists a draft DR, and lands on
    its detail view."""
    page = logged_in_sales_page
    page.goto(sales_e2e_server + DR_CREATE)
    page.wait_for_selector('#so-select')
    page.locator('#so-select').select_option(label='SO-E2E-0001: Acme Customer Inc')
    page.wait_for_selector('#dr-lines tbody tr')

    qty = page.locator('#dr-lines tbody tr .qty-input').first
    qty.fill('4')
    qty.dispatch_event('input')

    page.locator('#dr-form button[type="submit"]').click()
    # Land on the detail view /delivery-receipts/<id> (regex excludes /create).
    page.wait_for_url(re.compile(r'/delivery-receipts/\d+$'), timeout=15000)
    body = page.locator('body').inner_text()
    assert 'DR-' in body, body
