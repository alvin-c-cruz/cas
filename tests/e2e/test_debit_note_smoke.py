"""
Playwright e2e smoke for the Debit Note create grid (shares sales_memos_form.js with the
Credit Memo; the SI-lines fetch URL comes from the form's data attribute). Runs under the
`sales` seed profile (debit_memos ON + posted SI-E2E-0001).

Run: pytest -m credit_memos
"""
import re

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.credit_memos]

DN_CREATE = '/debit-notes/create'
SI_LABEL = 'SI-E2E-0001: Acme Customer Inc'


def test_debit_note_grid_loads_invoice_lines(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + DN_CREATE)
    page.wait_for_selector('#si-select')
    page.locator('#si-select').select_option(label=SI_LABEL)
    page.wait_for_selector('#memo-lines tbody tr')
    rows = page.evaluate("() => document.querySelectorAll('#memo-lines tbody tr').length")
    assert rows == 1
    assert '1000.00' in page.locator('#memo-lines tbody tr').first.inner_text()


def test_debit_note_round_trip_submit(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + DN_CREATE)
    page.wait_for_selector('#si-select')
    page.locator('#si-select').select_option(label=SI_LABEL)
    page.wait_for_selector('#memo-lines tbody tr')

    page.fill('#reason', 'Undercharge correction (e2e)')
    amt = page.locator('#memo-lines tbody tr .credit-input').first
    amt.fill('300')
    amt.dispatch_event('input')
    page.wait_for_function(
        "() => { const v = document.getElementById('lines-json').value; return v && v !== '[]'; }")

    page.locator('#memo-form button[type="submit"]').click()
    page.wait_for_url(re.compile(r'/debit-notes/\d+$'), timeout=15000)
    body = page.locator('body').inner_text()
    assert 'DM-' in body
    assert 'Draft' in body
