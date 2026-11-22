"""
Playwright e2e smoke tests for the Delivery Receipt form (delivery_receipts.js). pytest's HTML-only
tests never run this script, so this is its only browser coverage.

BUG-10 A (owner, 22 Nov 2026): the form follows the Sales Invoice form. The customer comes first; then
one plain choice, "Deliver against a sales order" (one of that customer's confirmed orders with open
lines) or "Deliver without a sales order"; one lines table for both.

Runs against its own seeded server (the Sales-cycle seed plus E2E_SEED_EXTRA=dr_form):
  Acme Customer Inc  one open order, SO-E2E-0001 (P001 Widget Standard, 10 PC, fully open)
  Borromeo Trading   no order
  Gamma Stores       two open orders, SO-E2E-0101 (P001, 6) and SO-E2E-0102 (P002 Gadget Deluxe, 8, PO 4411)

Run: python -m playwright install chromium   (once; or add --browser-channel msedge)
     pytest -m e2e tests/e2e/test_dr_smoke.py
"""
import json
import re

import pytest

from tests.e2e.conftest import _launch_seeded_server, _login_admin

pytestmark = [pytest.mark.e2e, pytest.mark.delivery_receipts]

DR_CREATE = '/delivery-receipts/create'
PICK_ONE = 'Select the sales order to deliver against, or choose "Deliver without a sales order".'
BIN = '\U0001F5D1'                       # the remove-line button, as on the SI form
CUSTOMER, ORDER = '#dr-customer', '#so-select'
SO_QTY = '#dr-so-body .qty-input'        # "Deliver now" on a line of the order


def free(n, part):
    """A control on the n-th line of a delivery without an order: 'product', 'unit', 'qty' or 'remove'."""
    css = {'product': '.dr-free-product', 'unit': '.dr-free-unit', 'qty': '.qty-input', 'remove': '.dr-remove-line'}
    return f'#dr-free-body tr:nth-child({n}) {css[part]}'


@pytest.fixture(scope='module')
def dr_server(tmp_path_factory):
    yield from _launch_seeded_server(tmp_path_factory, {'E2E_SEED_PROFILE': 'sales', 'E2E_SEED_EXTRA': 'dr_form'})


@pytest.fixture(scope='module')
def signed_in(browser, dr_server):
    """ONE sign-in for the whole file. /login takes 10 a minute, and this file has more tests than
    that: signing in per test made the 11th to 13th fail at the login page, not at the form."""
    context = browser.new_context()
    _login_admin(context.new_page(), dr_server)
    state = context.storage_state()
    context.close()
    return state


@pytest.fixture
def dr_page(browser, dr_server, signed_in):
    context = browser.new_context(storage_state=signed_in)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(dr_server + DR_CREATE)
    page.wait_for_selector('#dr-form')
    yield page
    context.close()
    assert errors == [], errors


def _widget(page, select_css):
    """The search-select (Choices) around a <select>. Choices takes the real <option>s out of the
    <select>, so the widget is driven, not the element."""
    return page.locator(select_css).locator(
        'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " choices ")][1]')


def pick(page, select_css, text):
    box = _widget(page, select_css)
    box.locator('.choices__inner').click()
    box.locator('.choices__list--dropdown .choices__item--selectable', has_text=text).first.click()


def shown(page, select_css):
    """What a search-select shows as chosen."""
    return _widget(page, select_css).locator('.choices__list--single .choices__item').inner_text().strip()


def _rows(page):
    """The visible cells of each visible line: an input's value, a search-select's chosen text, or the text."""
    return page.evaluate(
        """() => [...document.querySelectorAll('#lineItemsTable tbody tr')].filter(tr => tr.offsetParent !== null).map(tr =>
            [...tr.querySelectorAll('td')].filter(td => td.offsetParent !== null).map(td => {
                const inp = td.querySelector('input.form-control');
                if (inp) return inp.value;
                const chosen = td.querySelector('.choices__list--single .choices__item');
                return (chosen ? chosen.textContent : td.textContent).trim();
            }))""")


def _card(page):
    """The customer card's heading as written (the page shows it in capitals)."""
    return page.locator('#customerCardLabel').text_content().strip()


def _hidden(page, element_id):
    return page.locator(f'#{element_id}').input_value()


def _way(page, value):
    return page.locator(f'input[name="dr_source"][value="{value}"]')


def _save(page):
    page.locator('#dr-form button[type="submit"]').click()


def _saved(page):
    page.wait_for_url(re.compile(r'/delivery-receipts/\d+$'), timeout=15000)
    return page.locator('body').inner_text()


def _edit(page):
    page.goto(page.url + '/edit')
    page.wait_for_selector('#lineItemsTable tbody tr')


# --- the customer comes first ------------------------------------------------------------------------------------------

def test_nothing_is_open_until_a_customer_is_chosen(dr_page):
    page = dr_page
    assert _card(page) == 'Select Customer'
    assert page.locator('#lineItemsLocked').is_visible()
    assert page.locator('#drSourceSection').is_hidden()
    assert page.locator('#lineItemsSection').is_hidden()
    assert page.locator('#dr-form button[type="submit"]').is_hidden()


def test_a_customer_with_one_open_order_starts_on_that_order(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert _card(page) == '✓ C001 - Acme Customer Inc'
    assert page.locator('#lineItemsLocked').is_hidden()
    assert _way(page, 'so').is_checked()
    assert shown(page, ORDER).startswith('SO-E2E-0001 · ')
    assert int(_hidden(page, 'sales-order-id')) > 0

    rows = _rows(page)
    assert len(rows) == 1, rows
    line, product, uom, ordered, delivered, open_qty, deliver_now = rows[0]
    assert (line, product, uom, deliver_now) == ('1', 'P001: Widget Standard', 'PC', ''), rows
    assert (float(ordered), float(delivered), float(open_qty)) == (10.0, 0.0, 10.0), rows
    assert page.locator('#dr-no-lines').is_hidden()
    assert page.locator('#dr-add-line').is_hidden()          # the lines of an order are not added by hand


def test_a_typed_quantity_goes_into_the_hidden_field(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('4')

    lines = json.loads(_hidden(page, 'lines-json'))
    assert len(lines) == 1 and lines[0]['delivered_quantity'] == '4', lines
    assert isinstance(lines[0]['sales_order_item_id'], int), lines
    assert json.loads(_hidden(page, 'direct-lines-json')) == []


def test_a_delivery_against_an_order_saves(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('4')
    _save(page)
    body = _saved(page)
    assert re.search(r'\b\d{5}\b', body), body               # a plain five-digit DR number
    assert 'SO-E2E-0001' in body and 'Widget Standard' in body


# --- without a sales order ---------------------------------------------------------------------------------------------

def test_a_customer_with_no_open_order_delivers_without_one(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Borromeo Trading')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert _way(page, 'so').is_disabled()
    assert _way(page, 'none').is_checked()
    assert page.locator('#dr-no-orders').inner_text().strip() == (
        'This customer has no confirmed sales order with open lines.')
    assert _hidden(page, 'sales-order-id') == '0'
    assert _rows(page) == [['1', '— product —', "— product's unit —", '', BIN]]     # one empty line to start on
    assert page.locator('#dr-add-line').is_visible()
    # a card clips what hangs out of it; the pickers' dropdowns hang below the last line
    assert page.evaluate("() => [...document.querySelectorAll('.page-delivery-receipt, .page-delivery-receipt *')].filter(e => "
                         "e.contains(document.getElementById('lineItemsTable')) && "
                         "getComputedStyle(e).overflowY !== 'visible').map(e => e.className)") == []

    pick(page, free(1, 'product'), 'Widget Standard')
    assert shown(page, free(1, 'unit')) == 'PC'              # the product's own unit
    page.locator(free(1, 'qty')).fill('3')
    direct = json.loads(_hidden(page, 'direct-lines-json'))
    assert len(direct) == 1 and direct[0]['delivered_quantity'] == '3', direct
    assert int(direct[0]['product_id']) > 0 and int(direct[0]['uom_id']) > 0, direct
    assert json.loads(_hidden(page, 'lines-json')) == []

    _save(page)
    body = _saved(page)
    assert 'Borromeo Trading' in body and 'Widget Standard' in body and 'SO-E2E' not in body


def test_lines_without_an_order_are_added_and_removed(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Borromeo Trading')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator('#dr-add-line').click()
    assert [r[0] for r in _rows(page)] == ['1', '2']
    pick(page, free(2, 'product'), 'Gadget Deluxe')
    page.locator(free(2, 'qty')).fill('2')
    page.locator(free(1, 'remove')).click()
    assert _rows(page) == [['1', 'Gadget Deluxe', 'PC', '2', BIN]]       # renumbered from 1
    direct = json.loads(_hidden(page, 'direct-lines-json'))
    assert len(direct) == 1 and direct[0]['delivered_quantity'] == '2', direct


def test_a_half_filled_line_is_not_sent(dr_page, dr_server):
    """A product with no quantity would be dropped by the server without a word; the page says so first."""
    page = dr_page
    pick(page, CUSTOMER, 'Borromeo Trading')
    page.wait_for_selector('#lineItemsTable tbody tr')
    pick(page, free(1, 'product'), 'Widget Standard')
    _save(page)
    assert page.locator('#dr-lines-error').inner_text().strip() == (
        'Line 1: choose the product and enter a quantity above zero, or remove the line.')
    assert page.url == dr_server + DR_CREATE


# --- several open orders ------------------------------------------------------------------------------------------------

def test_a_customer_with_several_open_orders_must_pick_one(dr_page, dr_server):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    page.wait_for_selector('#lineItemsSection', state='visible')
    assert _way(page, 'so').is_checked()
    assert _hidden(page, 'sales-order-id') == ''
    assert _rows(page) == []
    assert page.locator('#dr-no-lines').inner_text().strip() == 'Select the sales order to load its open lines.'

    _save(page)                                              # no order named: nothing is sent
    assert page.locator('#dr-source-error').inner_text().strip() == PICK_ONE
    assert page.url == dr_server + DR_CREATE

    pick(page, ORDER, 'SO-E2E-0102')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert shown(page, ORDER).endswith(' · PO 4411')
    assert page.locator('#dr-source-error').is_hidden()
    rows = _rows(page)
    assert len(rows) == 1 and rows[0][1] == 'P002: Gadget Deluxe' and float(rows[0][3]) == 8.0, rows


def test_changing_the_way_keeps_what_was_typed(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('4')

    _way(page, 'none').check()
    assert _hidden(page, 'sales-order-id') == '0'
    assert json.loads(_hidden(page, 'lines-json')) == []     # the order's quantities are not sent this way
    pick(page, free(1, 'product'), 'Widget Standard')
    page.locator(free(1, 'qty')).fill('2')
    assert len(json.loads(_hidden(page, 'direct-lines-json'))) == 1

    _way(page, 'so').check()
    assert page.locator(SO_QTY).first.input_value() == '4'
    assert json.loads(_hidden(page, 'lines-json'))[0]['delivered_quantity'] == '4'
    assert json.loads(_hidden(page, 'direct-lines-json')) == []
    assert int(_hidden(page, 'sales-order-id')) > 0

    _way(page, 'none').check()
    assert _rows(page) == [['1', 'Widget Standard', 'PC', '2', BIN]]


def test_on_a_phone_the_lines_scroll_inside_their_box(browser, dr_server, signed_in):
    """A wide lines table must not push the whole page sideways on a narrow screen."""
    context = browser.new_context(storage_state=signed_in, viewport={'width': 430, 'height': 900})
    page = context.new_page()
    page.goto(dr_server + DR_CREATE)
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert page.evaluate('() => document.documentElement.scrollWidth - document.documentElement.clientWidth') == 0
    page.locator(SO_QTY).first.fill('4')                     # still reachable: scrolled into view inside the box
    assert json.loads(_hidden(page, 'lines-json'))[0]['delivered_quantity'] == '4'
    context.close()


def test_changing_the_customer_starts_the_order_over(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('4')
    pick(page, CUSTOMER, 'Gamma Stores')
    assert _card(page) == '✓ C003 - Gamma Stores'
    assert _hidden(page, 'sales-order-id') == ''
    assert json.loads(_hidden(page, 'lines-json')) == []     # Acme's order line is not carried to Gamma
    assert _rows(page) == []


# --- arriving with an order, editing, and a refused save ---------------------------------------------------------------

def test_coming_from_a_sales_order_opens_on_its_customer_and_the_order(dr_page, dr_server):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0102')
    so_id = _hidden(page, 'sales-order-id')
    page.goto(f'{dr_server}{DR_CREATE}?so={so_id}')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert _card(page) == '✓ C003 - Gamma Stores'
    assert shown(page, CUSTOMER) == 'C003 - Gamma Stores'
    assert _way(page, 'so').is_checked()
    assert shown(page, ORDER).startswith('SO-E2E-0102 · ')
    assert _rows(page)[0][1] == 'P002: Gadget Deluxe'


def test_editing_keeps_the_customer_and_the_order_and_changes_the_quantity(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Gamma Stores')
    pick(page, ORDER, 'SO-E2E-0101')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator(SO_QTY).first.fill('2')
    _save(page)
    _saved(page)

    _edit(page)
    assert _card(page) == '✓ C003 - Gamma Stores'
    assert page.locator(CUSTOMER).is_disabled() and page.locator(ORDER).is_disabled()
    assert _way(page, 'so').is_checked()
    assert _way(page, 'so').is_disabled() and _way(page, 'none').is_disabled()
    assert shown(page, ORDER).startswith('SO-E2E-0101 · ')
    qty = page.locator(SO_QTY).first
    assert qty.input_value() == '2'
    qty.fill('5')
    _save(page)
    assert 'updated' in _saved(page)
    _edit(page)
    assert page.locator(SO_QTY).first.input_value() == '5'


def test_editing_a_delivery_without_an_order(dr_page):
    page = dr_page
    pick(page, CUSTOMER, 'Borromeo Trading')
    page.wait_for_selector('#lineItemsTable tbody tr')
    pick(page, free(1, 'product'), 'Gadget Deluxe')
    page.locator(free(1, 'qty')).fill('7')
    _save(page)
    _saved(page)

    _edit(page)
    assert _way(page, 'none').is_checked()
    assert _way(page, 'so').is_disabled() and _way(page, 'none').is_disabled()
    assert page.locator('#dr-no-orders').is_hidden()         # a saved DR is not told about the customer's orders
    assert _rows(page) == [['1', 'Gadget Deluxe', 'PC', '7', BIN]]
    page.locator(free(1, 'qty')).fill('9')
    _save(page)
    _saved(page)
    _edit(page)
    assert _rows(page) == [['1', 'Gadget Deluxe', 'PC', '9', BIN]]


def test_a_refused_save_comes_back_as_it_was_left(dr_page, dr_server):
    page = dr_page
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator('#dr_number').fill('88001')
    page.locator(SO_QTY).first.fill('1')
    _save(page)
    _saved(page)

    page.goto(dr_server + DR_CREATE)
    pick(page, CUSTOMER, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsTable tbody tr')
    page.locator('#dr_number').fill('88001')                 # the same number again: refused
    page.locator(SO_QTY).first.fill('3')
    _save(page)
    page.wait_for_selector('text=already exists')
    page.wait_for_selector('#lineItemsTable tbody tr')
    assert _card(page) == '✓ C001 - Acme Customer Inc'
    assert shown(page, CUSTOMER) == 'C001 - Acme Customer Inc'
    assert _way(page, 'so').is_checked()
    assert shown(page, ORDER).startswith('SO-E2E-0001 · ')
    assert page.locator(SO_QTY).first.input_value() == '3'
