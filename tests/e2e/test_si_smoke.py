"""Playwright e2e smoke tests for the Sales Invoice create form — the JS/browser layer
that pytest's HTML-only tests can't see.

Run: python -m playwright install chromium   (once)
     pytest -m e2e

Marked `sales_invoices` too, so `pytest -m sales_invoices` exercises them as well.

Note: the customer picker is a Choices.js widget — selection MUST go through the Choices
UI (open the control, click the dropdown item), not the hidden native <select>.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]

SI_CREATE = '/sales-invoices/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'


def _pick_in_choices(page, scope_selector, text):
    """Open a Choices control and click the dropdown item containing `text`."""
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_first_line_item_added_when_customer_selected(logged_in_page, e2e_server):
    """Mirrors AP's vendor-select pattern: no line item until a customer is picked,
    then the first blank line is auto-added."""
    page = logged_in_page
    page.goto(e2e_server + SI_CREATE)
    page.wait_for_selector('#customer_id', state='attached')

    # No line items before a customer is chosen.
    assert page.locator('#lineItemsBody tr').count() == 0

    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')

    # Selecting a customer auto-adds exactly one blank line.
    page.wait_for_selector('#lineItemsBody tr')
    assert page.locator('#lineItemsBody tr').count() == 1
