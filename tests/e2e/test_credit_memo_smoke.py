"""
Playwright e2e smoke for the Credit Memo create grid -- the SI-select -> fetch-lines ->
enter-credit -> serialize JS (sales_memos_form.js) that pytest's HTML-only tests can't
execute. Runs under the `sales` seed profile (credit_memos ON + a posted SI-E2E-0001).

Posting a memo (JE + AR settlement) is covered by the integration tests; the browser
smoke covers the untested grid + a real create round-trip to a draft memo.

Run: pytest -m credit_memos
"""
import re

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.credit_memos]

CM_CREATE = '/credit-memos/create'
SI_LABEL = 'SI-E2E-0001: Acme Customer Inc'


def test_credit_memo_grid_loads_invoice_lines(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + CM_CREATE)
    page.wait_for_selector('#si-select')
    page.locator('#si-select').select_option(label=SI_LABEL)
    page.wait_for_selector('#memo-lines tbody tr')
    rows = page.evaluate("() => document.querySelectorAll('#memo-lines tbody tr').length")
    assert rows == 1
    # The invoice-amount cell shows the creditable line amount.
    assert '1000.00' in page.locator('#memo-lines tbody tr').first.inner_text()


def test_credit_memo_round_trip_submit(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + CM_CREATE)
    page.wait_for_selector('#si-select')
    page.locator('#si-select').select_option(label=SI_LABEL)
    page.wait_for_selector('#memo-lines tbody tr')

    page.fill('#reason', 'Returned goods (e2e)')
    amt = page.locator('#memo-lines tbody tr .credit-input').first
    amt.fill('400')
    amt.dispatch_event('input')
    page.wait_for_function(
        "() => { const v = document.getElementById('lines-json').value; return v && v !== '[]'; }")

    page.locator('#memo-form button[type="submit"]').click()
    # Lands on the detail view /credit-memos/<id> (regex excludes /create).
    page.wait_for_url(re.compile(r'/credit-memos/\d+$'), timeout=15000)
    body = page.locator('body').inner_text()
    assert 'CM-' in body
    assert 'Draft' in body        # a freshly created memo is a draft
