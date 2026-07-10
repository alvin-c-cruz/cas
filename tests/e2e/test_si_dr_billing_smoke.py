"""
Playwright e2e smoke for the SI form's DR-billing picker (si_dr_billing.js) -- the
JS integration that pulls a delivered DR's lines into the SI via addLineItem(). Runs
under the `sales` seed profile (a delivered DR-E2E-0001 for customer C001). The
save->bill server path is covered by the integration tests; this covers the browser JS.
"""
import json

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]

SI_CREATE = '/sales-invoices/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'


def _pick_in_choices(page, scope_selector, text):
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def test_si_form_pull_dr_populates_lines(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + SI_CREATE)
    page.wait_for_selector('#customer_id', state='attached')

    # Choose the customer that has the delivered DR.
    _pick_in_choices(page, CUSTOMER_SCOPE, 'Acme Customer Inc')

    # The DR-billing picker appears and lists the delivered DR.
    page.wait_for_selector('#drBillingSection', state='visible')
    page.wait_for_selector('.dr-pull-btn')
    assert 'DR-E2E-0001' in page.locator('#drBillingList').inner_text()

    # Count SI lines before pulling (the form auto-adds one on customer select).
    before = page.evaluate("() => document.querySelectorAll('#lineItemsBody tr').length")

    # Pull the DR -> its line is appended to the SI grid.
    page.locator('.dr-pull-btn').first.click()
    page.wait_for_function(
        "(n) => document.querySelectorAll('#lineItemsBody tr').length > n", arg=before)

    # The hidden source_dr_ids now carries the DR id.
    ids = json.loads(page.locator('#sourceDrIds').input_value())
    assert len(ids) == 1

    # Consolidation is OFF (default) -> the picker locked after the single pull.
    page.wait_for_selector('#drBillingLocked', state='visible')
