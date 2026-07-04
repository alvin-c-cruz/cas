"""
Playwright e2e smoke tests for CDV header Notes autofill (P-?? — "Paid <bill numbers>").

Notes (Particulars) autofills from the applied AP bills as Section A lines are added/
removed, live-updates on add/remove, and must never clobber text the user actually typed.

Run: python -m playwright install chromium   (once)
     pytest -m e2e            # or: pytest -m cash_disbursements

Fixture data: tests/e2e/_serve.py seeds vendor V001 with two open bills,
APV-2026-07-0001 (balance 1000) and APV-2026-07-0002 (balance 1500).
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_disbursements]

CDV_CREATE = '/cash-disbursements/create'
VENDOR_SCOPE = '.choices:has(#vendor_id)'


def _pick_in_choices(page, scope_selector, text):
    """Open a Choices control and click the dropdown item containing `text`."""
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _notes_value(page):
    return page.locator('textarea[name="notes"]').input_value()


def _add_bill_by_text(page, bill_number):
    scope = page.locator('.choices:has(#apBillPicker)')
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=bill_number).first.click()
    page.click("button:has-text('Add APV')")
    page.wait_for_function(
        "(num) => document.getElementById('apLinesBody').textContent.includes(num)",
        arg=bill_number, timeout=5000,
    )


def _remove_first_ap_row(page):
    page.locator('#apLinesBody tr').first.locator("button:has-text('X')").click()


def test_notes_autofills_with_one_bill(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')

    _add_bill_by_text(page, 'APV-2026-07-0001')
    assert _notes_value(page) == 'Paid APV-2026-07-0001'


def test_notes_autofills_comma_joined_with_two_bills(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')

    _add_bill_by_text(page, 'APV-2026-07-0001')
    _add_bill_by_text(page, 'APV-2026-07-0002')
    assert _notes_value(page) == 'Paid APV-2026-07-0001, APV-2026-07-0002'


def test_notes_updates_when_bill_removed(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')

    _add_bill_by_text(page, 'APV-2026-07-0001')
    _add_bill_by_text(page, 'APV-2026-07-0002')
    assert _notes_value(page) == 'Paid APV-2026-07-0001, APV-2026-07-0002'

    _remove_first_ap_row(page)
    page.wait_for_function(
        "() => document.querySelector('textarea[name=\"notes\"]').value === 'Paid APV-2026-07-0002'"
    )
    assert _notes_value(page) == 'Paid APV-2026-07-0002'


def test_custom_notes_survive_bill_add_and_remove(logged_in_page, e2e_server):
    """Typing into Notes must suppress autofill permanently for the rest of the session —
    adding/removing a settlement doc afterwards must NOT clobber the user's text."""
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')

    _add_bill_by_text(page, 'APV-2026-07-0001')
    assert _notes_value(page) == 'Paid APV-2026-07-0001'

    custom_text = 'Reimbursement per memo dated July 4'
    notes = page.locator('textarea[name="notes"]')
    notes.click()
    notes.fill(custom_text)
    # Real 'input' event fired by Playwright's fill() — confirm autofill is now suppressed.
    assert _notes_value(page) == custom_text

    _add_bill_by_text(page, 'APV-2026-07-0002')
    assert _notes_value(page) == custom_text, \
        'Autofill must not overwrite notes the user typed'

    _remove_first_ap_row(page)
    assert _notes_value(page) == custom_text, \
        'Autofill must not overwrite notes the user typed, even after a line is removed'
