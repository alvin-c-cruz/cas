"""
Playwright e2e smoke tests for the Cash Disbursement create form — the JS/browser layer
that pytest's HTML-only tests can't see. Regression net for the high-blast-radius shared
files (search-select.js, vendor-quick-add.js, transaction-utils.js, choices.min.js,
style.css) AND the CDV-specific browser behaviour: the live "Entry" JE-preview renderer
(renderCdvJEPreview) and the section-unlock flow.

Run: python -m playwright install chromium   (once)
     pytest -m e2e            # or: pytest -m cash_disbursements

Marked `cash_disbursements` so it can be run on its own. NOTE: this file is intentionally
NOT wired into the per-push regression guard yet (regression-map.json keeps cash_disbursements
"e2e": null) — the combined gate runs every module's smoke against one shared dev server that
degrades under cumulative load, so adding a module flakes the LAST module's dashboard login.
Run this manually / in CI until the e2e harness is hardened (server restart between modules
or a lighter login wait); then flip the map entry back to this path.

Note: the vendor / cash / account pickers are Choices.js widgets — Choices strips the real
options out of the native <select>, so selection MUST go through the Choices UI (open the
control, click the dropdown item), not the hidden native select.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.cash_disbursements]

CDV_CREATE = '/cash-disbursements/create'
DESC_SENTINEL = 'ZZTOPDESC_must_not_appear_in_account_title'

VENDOR_SCOPE = '.choices:has(#vendor_id)'
CASH_SCOPE = '.choices:has(#cash_account_id)'
ACCT_SCOPE = '.choices:has(select.acct-sel)'


def _pick_in_choices(page, scope_selector, text):
    """Open a Choices control and click the dropdown item containing `text`."""
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _add_expense_line(page, amount='1000', account_code='50226'):
    """Add a Section B direct-expense line and fill it (description sentinel + amount + account)."""
    page.click("button:has-text('Add Expense Line')")
    page.wait_for_selector('#expenseLinesBody tr')
    inputs = page.locator('#expenseLinesBody tr input.form-control')  # [0]=description, [1]=amount
    inputs.nth(0).fill(DESC_SENTINEL)
    inputs.nth(1).click()
    inputs.nth(1).fill(amount)
    page.keyboard.press('Tab')                 # blur -> expAmtBlur stores/formats the amount
    _pick_in_choices(page, ACCT_SCOPE, account_code)


def test_sections_unlock_when_vendor_selected(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    # Locked before a vendor is chosen.
    assert page.locator('#cdvSections').is_hidden()
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')


def test_entry_preview_shows_account_name_not_description(logged_in_page, e2e_server):
    """The live "Entry" (JE preview) Account Title column must show the ACCOUNT NAME,
    never the typed line description, and debits must equal credits (BUG-15 class)."""
    page = logged_in_page
    page.goto(e2e_server + CDV_CREATE)
    page.wait_for_selector('#vendor_id', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#cdvSections', state='visible')
    # Cr Cash needs a cash/bank account for the disbursement entry to balance.
    _pick_in_choices(page, CASH_SCOPE, 'Cash on Hand')
    _add_expense_line(page, amount='1000', account_code='50226')

    page.wait_for_selector('#jePreviewBody tr')
    data = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#jePreviewBody tr')];
            let debit = 0, credit = 0; const names = [];
            for (const r of rows) {
                const td = r.querySelectorAll('td');
                if (td.length < 4) continue;
                names.push(td[1].textContent.trim());
                debit  += parseFloat(td[2].textContent.replace(/[^0-9.\\-]/g, '')) || 0;
                credit += parseFloat(td[3].textContent.replace(/[^0-9.\\-]/g, '')) || 0;
            }
            return {debit, credit, names,
                    bodyText: document.querySelector('#jePreviewBody').innerText};
        }"""
    )

    # The typed description must NOT leak into the Account Title column (or anywhere in preview).
    assert DESC_SENTINEL not in data['bodyText'], \
        'Entry preview Account Title shows the line description instead of the account name (BUG-15 class)'
    # Both the expense account and the cash account NAMES should be present.
    assert any('Office Supplies' in n for n in data['names']), \
        f"expected the expense account name in the preview, got names={data['names']}"
    assert any('Cash on Hand' in n for n in data['names']), \
        f"expected the cash account name in the preview, got names={data['names']}"
    # Double-entry: debits == credits (Dr Office Supplies / Cr Cash).
    assert abs(data['debit'] - data['credit']) < 0.01, \
        f"Entry preview not balanced: debit={data['debit']} credit={data['credit']}"
