import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.smoke


def test_page_loads_with_disabled_submit(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#lineItemsSection')).to_be_hidden()


def test_submit_still_disabled_after_vendor_no_invoice(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('vendor invoice number')


def test_submit_still_disabled_with_invoice_but_no_account(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    page.fill('#vendor_invoice_number', 'INV-001')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('account title')


def test_submit_enabled_when_all_required_fields_present(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/purchase-bills/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    page.fill('#vendor_invoice_number', 'INV-001')

    # Enter amount on first row
    amount_input = page.locator('#lineItemsBody tr:first-child input[type="text"]').first
    amount_input.click()
    amount_input.fill('1000.00')
    amount_input.press('Tab')

    # Open account Choices.js dropdown and pick the first real option
    page.locator('#lineItemsBody tr:first-child .choices[data-type*=select-one]').last.click()
    page.wait_for_selector('.choices__list--dropdown .choices__item--selectable:not(.choices__item--disabled)', timeout=3000)
    page.locator('.choices__list--dropdown .choices__item--selectable:not(.choices__item--disabled)').first.click()

    expect(page.locator('#submitBtn')).to_be_enabled(timeout=3000)
