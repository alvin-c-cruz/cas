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

    # Count SI lines before pulling (the form auto-adds one untouched blank starter line
    # on customer select).
    before = page.evaluate("() => document.querySelectorAll('#lineItemsBody tr').length")

    # Pull the DR -> its line is appended to the SI grid. Wait on source_dr_ids (the
    # picker's own completion signal) rather than a row-count increase: BUG-SI-PULL-DR-
    # LEAVES-BLANK-LINE's fix (5bd9e207) makes pull() call removeBlankStarterLine() FIRST,
    # so the untouched blank line here is replaced, not kept alongside the pulled line --
    # a bare `count > before` wait would time out forever against the fixed behavior.
    page.locator('.dr-pull-btn').first.click()
    page.wait_for_function(
        "() => { try { return JSON.parse(document.getElementById('sourceDrIds').value).length > 0; } "
        "catch (e) { return false; } }")

    # The hidden source_dr_ids now carries the DR id.
    ids = json.loads(page.locator('#sourceDrIds').input_value())
    assert len(ids) == 1

    # BUG-SI-PULL-DR-LEAVES-BLANK-LINE regression guard: the blank starter line was
    # REPLACED (not kept alongside), so the row count is unchanged, not incremented.
    after = page.evaluate("() => document.querySelectorAll('#lineItemsBody tr').length")
    assert after == before, (
        f"expected the blank starter line to be replaced by the pulled DR line "
        f"(before={before}, after={after}) -- BUG-SI-PULL-DR-LEAVES-BLANK-LINE regressed"
    )

    # Consolidation is OFF (default) -> the picker locked after the single pull.
    page.wait_for_selector('#drBillingLocked', state='visible')
