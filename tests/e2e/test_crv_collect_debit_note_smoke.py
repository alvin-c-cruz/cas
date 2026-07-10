"""
Playwright e2e smoke: the CRV open-items picker unions in a posted debit note (Phase 2b),
lands it as an AR row tagged "Debit Note", and serializes it with type='debit_note' so the
server parser routes the collection to the debit note (not a Sales Invoice).

Runs under the `sales` seed profile (debit_memos ON + posted SI-E2E-0001 + posted debit
note DM-E2E-0001, balance 560). Browser-only coverage the integration parser test can't
give: that JSON.stringify(arLines) actually carries `type` through a real submit.

Run: pytest -m cash_receipts
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_receipts]

CRV_CREATE = '/cash-receipts/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'
DN_NUMBER = 'DM-E2E-0001'


def _pick_in_choices(page, scope_selector, text):
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _add_open_item_by_text(page, number):
    scope = page.locator('.choices:has(#arInvPicker)')
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=number).first.click()
    page.click("button:has-text('Add Invoice')")
    page.wait_for_function(
        "(num) => document.getElementById('arLinesBody').textContent.includes(num)",
        arg=number, timeout=5000,
    )


def test_crv_picker_collects_a_debit_note(logged_in_sales_page, sales_e2e_server):
    page = logged_in_sales_page
    page.goto(sales_e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')
    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')
    page.wait_for_selector('#crvSections', state='visible')

    _add_open_item_by_text(page, DN_NUMBER)

    # The AR row shows the debit note number and the "Debit Note" badge.
    row_text = page.locator('#arLinesBody tr', has_text=DN_NUMBER).first.inner_text()
    assert DN_NUMBER in row_text
    assert 'DEBIT NOTE' in row_text.upper()      # badge text (CSS uppercases it)

    # serializeData() must carry type='debit_note' so the server routes the collection
    # to the SalesMemo (the exact browser-only path the parser integration test stubs).
    payload = page.evaluate(
        "() => { serializeData(); return document.getElementById('arLinesData').value; }")
    assert '"type":"debit_note"' in payload.replace(' ', '')
