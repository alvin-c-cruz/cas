"""
Playwright e2e smoke tests for CRV header Notes autofill (mirrors CDV — "Collected
<invoice numbers>"). Notes (Particulars) autofills from the applied AR invoices as
Section A lines are added/removed, live-updates on add/remove, and must never clobber
text the user actually typed.

Run: python -m playwright install chromium   (once)
     pytest -m e2e            # or: pytest -m cash_receipts

Fixture data: tests/e2e/_serve.py seeds customer C001 with two open invoices,
SI-2026-07-0001 (balance 2000) and SI-2026-07-0002 (balance 2500).
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_receipts]

CRV_CREATE = '/cash-receipts/create'
CUSTOMER_SCOPE = '.choices:has(#customer_id)'


def _pick_in_choices(page, scope_selector, text):
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _notes_value(page):
    return page.locator('textarea[name="notes"]').input_value()


def _add_invoice_by_text(page, invoice_number):
    scope = page.locator('.choices:has(#arInvPicker)')
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=invoice_number).first.click()
    page.click("button:has-text('Add Invoice')")
    page.wait_for_function(
        "(num) => document.getElementById('arLinesBody').textContent.includes(num)",
        arg=invoice_number, timeout=5000,
    )


def _remove_first_ar_row(page):
    page.locator('#arLinesBody tr').first.locator("button:has-text('X')").click()


def test_notes_autofills_with_one_invoice(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')
    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')
    page.wait_for_selector('#crvSections', state='visible')

    _add_invoice_by_text(page, 'SI-2026-07-0001')
    assert _notes_value(page) == 'Collected SI-2026-07-0001'


def test_notes_autofills_comma_joined_with_two_invoices(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')
    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')
    page.wait_for_selector('#crvSections', state='visible')

    _add_invoice_by_text(page, 'SI-2026-07-0001')
    _add_invoice_by_text(page, 'SI-2026-07-0002')
    assert _notes_value(page) == 'Collected SI-2026-07-0001, SI-2026-07-0002'


def test_notes_updates_when_invoice_removed(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')
    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')
    page.wait_for_selector('#crvSections', state='visible')

    _add_invoice_by_text(page, 'SI-2026-07-0001')
    _add_invoice_by_text(page, 'SI-2026-07-0002')
    assert _notes_value(page) == 'Collected SI-2026-07-0001, SI-2026-07-0002'

    _remove_first_ar_row(page)
    page.wait_for_function(
        "() => document.querySelector('textarea[name=\"notes\"]').value === 'Collected SI-2026-07-0002'"
    )
    assert _notes_value(page) == 'Collected SI-2026-07-0002'


def test_custom_notes_survive_invoice_add_and_remove(logged_in_page, e2e_server):
    """Typing into Notes must suppress autofill permanently for the rest of the session —
    adding/removing a settlement doc afterwards must NOT clobber the user's text."""
    page = logged_in_page
    page.goto(e2e_server + CRV_CREATE)
    page.wait_for_selector('#customer_id', state='attached')
    _pick_in_choices(page, CUSTOMER_SCOPE, 'C001')
    page.wait_for_selector('#crvSections', state='visible')

    _add_invoice_by_text(page, 'SI-2026-07-0001')
    assert _notes_value(page) == 'Collected SI-2026-07-0001'

    custom_text = 'Collection per official receipt dated July 4'
    notes = page.locator('textarea[name="notes"]')
    notes.click()
    notes.fill(custom_text)
    assert _notes_value(page) == custom_text

    _add_invoice_by_text(page, 'SI-2026-07-0002')
    assert _notes_value(page) == custom_text, \
        'Autofill must not overwrite notes the user typed'

    _remove_first_ar_row(page)
    assert _notes_value(page) == custom_text, \
        'Autofill must not overwrite notes the user typed, even after a line is removed'
