"""
Playwright e2e smoke tests for the Quotation create form — the line-grid JS layer
that pytest's HTML-only tests can't execute. Covers the customer-unlock gate, product
autofill (unit price from the product default), the treatment-aware totals math
(inclusive vs exclusive), and a full round-trip submit that persists the quotation.

These run against the `sales_e2e_server` (Sales-cycle modules ON + products + a
confirmed SO seeded), isolated from the lean AP/SI seed so the toggles never touch
the other smokes.

Run: python -m playwright install chromium   (once)
     pytest -m quotations
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.quotations]

QUOTE_CREATE = '/quotations/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id_display)'


def _pick_in_choices(page, scope_selector, text):
    """Open a Choices control and click the dropdown item containing `text`."""
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _totals(page):
    return page.evaluate(
        """() => ({
            subtotal: document.getElementById('subtotalDisplay').textContent.trim(),
            vat:      document.getElementById('vatDisplay').textContent.trim(),
            total:    document.getElementById('totalDisplay').textContent.trim(),
        })"""
    )


def _select_customer_and_first_line(page, base):
    """Open the create form, pick the seeded customer (unlocks + auto-adds line 1)."""
    page.goto(base + QUOTE_CREATE)
    page.wait_for_selector('#customer_id_display', state='attached')
    # Line items are locked until a customer is chosen.
    assert page.locator('#lineItemsSection').is_hidden()
    _pick_in_choices(page, CUSTOMER_SCOPE, 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsSection', state='visible')
    # The first line is auto-added (id == 1, lineCounter starts at 0).
    page.wait_for_selector('#lineItemsBody tr')


def test_customer_unlocks_and_product_autofills(logged_in_sales_page, sales_e2e_server):
    """Selecting a customer reveals the grid; picking a product fills the unit price
    from the product default and the amount derives from qty x unit price."""
    page = logged_in_sales_page
    _select_customer_and_first_line(page, sales_e2e_server)

    # Pick the first real product (P001, default unit price 100.00) in line 1.
    row = page.locator('#line-1')
    row.locator('td select').first.select_option(index=1)   # 0 == placeholder
    # Unit price auto-filled from the product default (number input normalises 100.0 -> "100").
    page.wait_for_function(
        "() => { const el = document.getElementById('up-1'); return el && parseFloat(el.value) === 100; }"
    )
    # Set quantity -> amount derives (qty x unit price).
    qty = row.locator('#qty-1')
    qty.fill('2')
    qty.dispatch_event('change')
    page.wait_for_function(
        "() => document.getElementById('amt-1') && document.getElementById('amt-1').value.replace(/,/g,'') === '200.00'"
    )
    # Inclusive (default) treatment: total == subtotal == 200.00, VAT extracted (V0 -> 0).
    t = _totals(page)
    assert t['subtotal'] == '200.00', t
    assert t['total'] == '200.00', t
    # Submit button enabled once a line has an amount > 0.
    assert page.locator('#submitBtn').is_enabled()


def test_vat_treatment_switches_totals_math(logged_in_sales_page, sales_e2e_server):
    """Switching the header VAT treatment to exclusive adds 12% on top of the net
    subtotal (inclusive extracts, exclusive adds)."""
    page = logged_in_sales_page
    _select_customer_and_first_line(page, sales_e2e_server)

    row = page.locator('#line-1')
    row.locator('td select').first.select_option(index=1)
    qty = row.locator('#qty-1')
    qty.fill('2')
    qty.dispatch_event('change')
    page.wait_for_function(
        "() => document.getElementById('amt-1') && document.getElementById('amt-1').value.replace(/,/g,'') === '200.00'"
    )

    # Exclusive: subtotal 200 net, VAT = 200 x 12% = 24, total = 224.
    treatment = page.locator('#vat_treatment')
    treatment.select_option('exclusive')
    treatment.dispatch_event('change')
    page.wait_for_function(
        "() => document.getElementById('vatDisplay').textContent.trim() === '24.00'"
    )
    t = _totals(page)
    assert t['subtotal'] == '200.00', t
    assert t['vat'] == '24.00', t
    assert t['total'] == '224.00', t


def test_quotation_round_trip_submit(logged_in_sales_page, sales_e2e_server):
    """A filled quotation submits, persists, and lands on its read-only detail view."""
    page = logged_in_sales_page
    _select_customer_and_first_line(page, sales_e2e_server)

    row = page.locator('#line-1')
    row.locator('td select').first.select_option(index=1)
    qty = row.locator('#qty-1')
    qty.fill('3')
    qty.dispatch_event('change')
    page.wait_for_function(
        "() => document.getElementById('amt-1') && document.getElementById('amt-1').value.replace(/,/g,'') === '300.00'"
    )

    page.locator('#submitBtn').click()
    # Redirects to the detail view (/quotations/<id>) with a success flash.
    page.wait_for_url('**/quotations/*', timeout=15000)
    body = page.locator('body').inner_text()
    assert 'created successfully' in body or 'QTN-' in body, body
