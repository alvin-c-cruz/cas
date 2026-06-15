import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.accounts_payable, pytest.mark.smoke]


def test_page_loads_with_disabled_submit(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#lineItemsSection')).to_be_hidden()


def test_submit_still_disabled_after_vendor_no_invoice(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('vendor invoice number')


def test_submit_still_disabled_with_invoice_but_no_account(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    page.fill('#vendor_invoice_number', 'INV-001')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('account title')


def test_submit_enabled_when_all_required_fields_present(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    page.select_option('#vendor_id', label='SUP001 - Test Supplier')
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)
    page.fill('#vendor_invoice_number', 'INV-001')

    # Enter amount on first row — td:nth-child(2) holds the amount input
    amount_input = page.locator('#lineItemsBody tr:first-child td:nth-child(2) input[type="text"]')
    amount_input.click()
    amount_input.fill('1000.00')
    # Trigger blur explicitly so amtBlur fires and updates lineItems[].amount
    page.evaluate("() => { const el = document.querySelector('#lineItemsBody tr:first-child td:nth-child(2) input[type=\"text\"]'); if(el){ el.blur(); } }")

    # Use the first real (non-group) account ID from the JS allAccounts array via evaluate
    page.evaluate("""() => {
        const firstAcct = allAccounts.find(a => !a.is_group);
        if (firstAcct && lineItems.length > 0) {
            updateLineItem(lineItems[0].id, 'account_id', firstAcct.id);
        }
    }""")

    expect(page.locator('#submitBtn')).to_be_enabled(timeout=3000)
