import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.accounts_payable, pytest.mark.smoke]


def _select_vendor(page, label='Test Supplier'):
    """Pick a vendor through the combined payee Choices.js UI.

    #payee is a Choices picker, which strips the native <option>s — so
    page.select_option() times out. Open the widget and click the item instead.
    Selecting fires a native 'change' that reveals the line-items section.
    `label` is a substring — the option now renders "SUP001 : Test Supplier [Vendor]".
    """
    scope = page.locator('.choices:has(#payee)')
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item--choice',
                  has_text=label).first.click()
    page.wait_for_selector('#lineItemsSection', state='visible', timeout=5000)


def test_page_loads_with_disabled_submit(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#lineItemsSection')).to_be_hidden()


def test_submit_still_disabled_after_vendor_no_notes(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    _select_vendor(page)
    # Vendor invoice # is intentionally NOT required to save a draft (it is
    # enforced at POST when VAT/WHT applies). The first remaining blocker after
    # selecting a vendor is the required notes / particulars field.
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('notes')


def test_submit_still_disabled_with_notes_but_no_account(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    _select_vendor(page)
    page.fill('textarea[name="notes"]', 'Test particulars')
    # Clear the line's account so the account-title blocker is what surfaces
    # (updateLineItem re-runs validateForm). Account is checked before amount.
    page.evaluate("() => { if (lineItems.length) updateLineItem(lineItems[0].id, 'account_id', null); }")
    expect(page.locator('#submitBtn')).to_be_disabled()
    expect(page.locator('#saveHint')).to_contain_text('account title')


def test_submit_enabled_when_all_required_fields_present(logged_in_page):
    page, base = logged_in_page
    page.goto(f'{base}/accounts-payable/create')
    _select_vendor(page)
    page.fill('textarea[name="notes"]', 'Test particulars')

    # Enter amount on first row — use stable id prefix; td:nth-child(2) broke when
    # P-56 added Qty/UOM/UP columns before Amount
    amount_input = page.locator('#lineItemsBody tr:first-child input[id^="amt-"]')
    amount_input.click()
    amount_input.fill('1000.00')
    # Trigger blur explicitly so amtBlur fires and updates lineItems[].amount
    page.evaluate("() => { const el = document.querySelector('#lineItemsBody tr:first-child input[id^=\"amt-\"]'); if(el){ el.blur(); } }")

    # Use the first real (non-group) account ID from the JS allAccounts array via evaluate
    page.evaluate("""() => {
        const firstAcct = allAccounts.find(a => !a.is_group);
        if (firstAcct && lineItems.length > 0) {
            updateLineItem(lineItems[0].id, 'account_id', firstAcct.id);
        }
    }""")

    expect(page.locator('#submitBtn')).to_be_enabled(timeout=3000)
