"""
Playwright e2e smoke test for the inline "Add product" box (product-quick-add.js), shared by eight transaction forms.

PROD-QA (owner, 22 Nov 2026: "the two should be identical"): the box shows the Products form's own fields. Here, on
the Sales Order form: the box opens from a line's product picker, takes the unit, allowed units, price and inventory
unit; the line then takes the new product's unit and price, and the company-inventory columns use its factor. The box
opens empty again for the next product.

Runs against the Sales-cycle seed server (products, units of measure, sales orders on; customer Acme; unit PC).
Run: pytest -m e2e tests/e2e/test_product_quick_add_smoke.py --browser-channel msedge
"""
import re

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_orders]


def _widget(page, css):
    return page.locator(css).locator(
        'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " choices ")][1]')


def _pick(page, css, text):
    box = _widget(page, css)
    page.wait_for_timeout(250)
    if 'is-open' not in (box.get_attribute('class') or '').split():
        box.locator('.choices__inner').click()
        page.wait_for_timeout(250)
    box.locator('.choices__list--dropdown .choices__item--selectable', has_text=text).first.click()
    page.wait_for_timeout(250)


def _shown(page, css):
    return _widget(page, css).locator('.choices__list--single .choices__item').inner_text().strip()


def test_a_product_added_from_a_sales_order_line(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    # A second unit, so the line (in PC) and the company inventory (in KG) differ: the SO shows the inventory columns
    # only then.
    page.goto(sales_e2e_server + '/units-of-measure/create')
    page.fill('#code', 'KG')
    page.fill('#name', 'Kilogram')
    page.click('form button[type="submit"]')
    page.wait_for_load_state('networkidle')
    page.goto(sales_e2e_server + '/sales-orders/create')
    page.wait_for_load_state('networkidle')
    _pick(page, '#customer_id_display', 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.click('#addLineBtn')
    page.wait_for_selector('#prod-sel-1', state='attached')

    _pick(page, '#prod-sel-1', '+ Add Product')
    page.wait_for_selector('#productQuickAddOverlay', state='visible')
    box = page.locator('#productQuickAddForm')
    labels = [t.strip() for t in box.locator('label').all_text_contents()]   # as written (shown in capitals)
    for label in ('Name', "Customer's Product Code", 'Description', 'Job Order Name', 'Default Unit of Measure',
                  'Default Account', 'Allowed Units (no-PO receiving)', 'Category', 'Default Unit Price',
                  'Standard Cost', 'Inventory Unit', 'Inventory Qty per Unit', 'Status'):
        assert any(label in t for t in labels), (label, labels)
    assert page.evaluate('() => document.activeElement && document.activeElement.id') == 'pqa-name'

    page.fill('#pqa-name', 'BOX DRIED MANGO 100g')
    page.select_option('#pqa-default_unit_of_measure_id', label='PC — Piece')
    page.select_option('#pqa-allowed_unit_ids', label=['PC — Piece'])
    page.fill('#pqa-default_unit_price', '55')
    page.select_option('#pqa-inventory_unit_id', label='KG — Kilogram')
    page.fill('#pqa-inventory_qty_per_unit', '0.1')
    page.click('#productQuickAddSubmit')
    page.wait_for_selector('#productQuickAddOverlay', state='hidden', timeout=15000)

    assert _shown(page, '#prod-sel-1') == 'BOX DRIED MANGO 100g'
    pc = page.evaluate("() => String(units.find(u => u.code === 'PC').id)")
    assert page.locator('#uom-sel-1').input_value() == pc      # the product's unit (the picker shows its name)
    assert float(page.locator('#up-1').input_value().replace(',', '')) == 55.0
    page.fill('#qty-1', '3')
    page.locator('#qty-1').blur()
    page.wait_for_timeout(300)
    assert float(page.locator('#invq-1').inner_text().replace(',', '')) == 0.3        # 3 packs x 0.1 KG
    assert page.locator('#invu-1').inner_text().strip() == 'KG'

    # The next product starts from an empty box, Active.
    page.click('#addLineBtn')
    page.wait_for_selector('#prod-sel-2', state='attached')
    _pick(page, '#prod-sel-2', '+ Add Product')
    page.wait_for_selector('#productQuickAddOverlay', state='visible')
    assert page.locator('#pqa-name').input_value() == ''
    assert page.locator('#pqa-default_unit_price').input_value() == ''
    assert page.locator('#pqa-is_active').input_value() == '1'
    page.click('#productQuickAddCancel')
    page.wait_for_selector('#productQuickAddOverlay', state='hidden')

    page.goto(sales_e2e_server + '/products')
    page.wait_for_load_state('networkidle')
    assert 'BOX DRIED MANGO 100g' in page.locator('body').inner_text()
    assert errors == [], errors


def test_a_refused_product_says_why_and_keeps_what_was_typed(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + '/sales-orders/create')
    page.wait_for_load_state('networkidle')
    _pick(page, '#customer_id_display', 'Acme Customer Inc')
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.click('#addLineBtn')
    _pick(page, '#prod-sel-1', '+ Add Product')
    page.wait_for_selector('#productQuickAddOverlay', state='visible')
    page.fill('#pqa-default_unit_price', '-5')                    # no name, and a negative price
    page.click('#productQuickAddSubmit')
    page.wait_for_selector('#productQuickAddError', state='visible')
    assert re.search(r'required|must be', page.locator('#productQuickAddError').inner_text(), re.I)
    assert page.locator('#productQuickAddOverlay').is_visible()
    assert page.locator('#pqa-default_unit_price').input_value() == '-5'
