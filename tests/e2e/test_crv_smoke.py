"""Playwright e2e smoke for the Cash Receipt create form customer quick-add."""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_receipts]

CRV_CREATE = '/cash-receipts/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'


def _pick_in_choices(page, scope_selector, text):
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_add_customer_modal_creates_and_selects(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')

    _pick_in_choices(page, CUSTOMER_SCOPE, 'Add Customer')
    overlay = page.locator('#customerQuickAddOverlay')
    overlay.wait_for(state='visible')

    new_name = 'E2E CRV Customer LLC'
    overlay.locator('input[name="name"]').fill(new_name)
    page.click('#customerQuickAddSubmit')

    overlay.wait_for(state='hidden')
    page.wait_for_function(
        """(name) => {
            const chip = document.querySelector('.choices:has(#customer_id) .choices__list--single .choices__item');
            return chip && chip.textContent.includes(name);
        }""",
        arg=new_name, timeout=10000,
    )
