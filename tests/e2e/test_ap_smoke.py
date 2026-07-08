"""
Playwright e2e smoke tests for the Accounts Payable create form — the JS/browser layer
that pytest's HTML-only tests can't see. These are the regression net for the high-blast-
radius shared files (search-select.js, vendor-quick-add.js, transaction-utils.js, the JE
preview renderer) listed in .claude/regression-map.json.

Run: python -m playwright install chromium   (once)
     pytest -m e2e

Marked `accounts_payable` too, so `pytest -m accounts_payable` (what /guard runs for AP)
exercises them as well.

Note: the vendor/account pickers are Choices.js widgets — Choices strips the real options
out of the native <select>, so selection MUST go through the Choices UI (open the control,
click the dropdown item), not the hidden native select.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.accounts_payable]

AP_CREATE = '/accounts-payable/create'
DESC_SENTINEL = 'ZZTOPDESC_must_not_appear_in_account_title'

VENDOR_SCOPE = '.choices:has(#payee)'
ACCT_SCOPE = '.choices:has(select.acct-select)'


def _pick_in_choices(page, scope_selector, text):
    """Open a Choices control and click the dropdown item containing `text`."""
    scope = page.locator(scope_selector)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text=text).first.click()


def _selected_vendor_text(page):
    chip = page.locator(f'{VENDOR_SCOPE} .choices__list--single .choices__item')
    return chip.inner_text() if chip.count() else ''


def _fill_first_line(page, amount='1000', account_code='50226'):
    # P-56 added Qty / UOM / Unit-Price columns, so the amount is the `amt-` input, NOT the
    # 2nd input in the row (that is now Quantity). Target amount by id; filling Qty alone
    # leaves amount=0 (amount only derives when both qty AND unit_price are set), which made
    # this JE-preview assertion pass VACUOUSLY on an all-zero entry.
    row = page.locator('#lineItemsBody tr').first
    row.locator('input[id^="desc-"]').first.fill(DESC_SENTINEL)
    amt = row.locator('input[id^="amt-"]').first   # the amount field (qty/unit-price left blank)
    amt.click()
    amt.fill(amount)
    page.keyboard.press('Tab')                 # blur -> amtBlur stores/formats the amount
    _pick_in_choices(page, ACCT_SCOPE, account_code)


def test_line_items_unlock_when_vendor_selected(logged_in_page, e2e_server):
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')
    # Locked before a vendor is chosen.
    assert page.locator('#lineItemsSection').is_hidden()
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#lineItemsSection', state='visible')
    # A first line is auto-added.
    page.wait_for_selector('#lineItemsBody tr')
    assert page.locator('#lineItemsBody tr').count() >= 1


def test_je_preview_shows_account_name_not_description(logged_in_page, e2e_server):
    """BUG-15 class: the JE preview 'Account Title' column must show the ACCOUNT NAME,
    never the line description, and debits must equal credits."""
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#lineItemsSection', state='visible')
    _fill_first_line(page, amount='1000', account_code='50226')

    page.wait_for_selector('#jePreviewBody tr')
    data = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#jePreviewBody tr')];
            let debit = 0, credit = 0; const names = []; const codes = [];
            for (const r of rows) {
                const td = r.querySelectorAll('td');
                if (td.length < 4) continue;
                codes.push(td[0].textContent.trim());
                names.push(td[1].textContent.trim());
                debit  += parseFloat(td[2].textContent.replace(/[^0-9.\\-]/g, '')) || 0;
                credit += parseFloat(td[3].textContent.replace(/[^0-9.\\-]/g, '')) || 0;
            }
            return {debit, credit, names, codes,
                    bodyText: document.querySelector('#jePreviewBody').innerText};
        }"""
    )

    # The typed description must NOT leak into the Account Title column (or anywhere in preview).
    assert DESC_SENTINEL not in data['bodyText'], \
        'JE preview Account Title shows the line description instead of the account name (BUG-15 class)'
    # The expense account's NAME should be present.
    assert any('Office Supplies' in n for n in data['names']), \
        f"expected the account name in the preview, got names={data['names']}"
    # Double-entry: debits == credits.
    assert abs(data['debit'] - data['credit']) < 0.01, \
        f"JE preview not balanced: debit={data['debit']} credit={data['credit']}"


def _first_wht_choices_class(page):
    """Return the CSS class string of the WT Choices wrapper in the first line item row."""
    return (
        page.locator('#lineItemsBody tr:first-child .choices:has(.wht-select)')
            .get_attribute('class') or ''
    )


def test_wt_scoping_tracks_vendor(logged_in_page, e2e_server):
    """WT dropdown state must follow vendor selection.

    V001 has WC100 assigned → WT enabled.
    Switch to V002 (no WHT codes) → WT disabled with an explanatory notice.
    """
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')

    # V001 has WC100 — line items unlock, WT dropdown initialises enabled.
    _pick_in_choices(page, VENDOR_SCOPE, 'V001')
    page.wait_for_selector('#lineItemsSection', state='visible')
    page.wait_for_selector('#lineItemsBody tr')
    page.wait_for_function(
        "() => !!document.querySelector('#lineItemsBody tr .choices:has(.wht-select)')"
    )
    assert 'is-disabled' not in _first_wht_choices_class(page), \
        'WT dropdown should be ENABLED for V001 which has WC100 assigned'

    # Switch to V002 — no WHT codes assigned.
    _pick_in_choices(page, VENDOR_SCOPE, 'V002')
    page.wait_for_function(
        "() => document.querySelector('#lineItemsBody tr .choices:has(.wht-select)')"
        "?.classList.contains('is-disabled')"
    )
    assert 'is-disabled' in _first_wht_choices_class(page), \
        'WT dropdown should be DISABLED for V002 which has no WHT codes'

    # The visible label must explain why (not a confusing blank / "None").
    selected_label = page.locator(
        '#lineItemsBody tr:first-child .choices:has(.wht-select) '
        '.choices__list--single .choices__item'
    ).first.inner_text()
    assert 'No WT' in selected_label, \
        f'WT dropdown should display a "No WT" notice, got: {selected_label!r}'


def test_presave_upload_card_renders_on_create(logged_in_page, e2e_server):
    """The file-upload card must be present and wired up before any save."""
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#createAttachments')

    upload = page.locator('#createAttachments')
    assert upload.get_attribute('multiple') is not None, \
        'File input must carry the multiple attribute'
    assert upload.get_attribute('name') == 'attachments', \
        'File input must be named "attachments"'

    form = page.locator('#billForm')
    assert form.get_attribute('enctype') == 'multipart/form-data', \
        'Form enctype must be multipart/form-data for file upload to work'

    assert page.locator('#attachmentQueue').count() == 1, \
        '#attachmentQueue (the JS file-list) must be present'


def test_quick_add_modal_opens_and_selects_new_vendor(logged_in_page, e2e_server):
    """The inline '+ Add Vendor' modal must open, create a vendor, auto-select it, and
    leave the line items unlocked."""
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')

    # Open the picker and click the add-vendor action.
    _pick_in_choices(page, VENDOR_SCOPE, 'Add Vendor')
    overlay = page.locator('#vendorQuickAddOverlay')
    overlay.wait_for(state='visible')

    new_name = 'E2E Quick Vendor LLC'
    overlay.locator('input[name="name"]').fill(new_name)
    # Default VAT category is required by the vendor form.
    _pick_in_choices(page, '.choices:has(#default_vat_category)', 'VEX')
    page.click('#vendorQuickAddSubmit')

    # Modal closes and the new vendor becomes the selected chip.
    overlay.wait_for(state='hidden')
    page.wait_for_function(
        """(name) => {
            const chip = document.querySelector('.choices:has(#payee) .choices__list--single .choices__item');
            return chip && chip.textContent.includes(name);
        }""",
        arg=new_name,
        timeout=10000,
    )
    assert new_name in _selected_vendor_text(page)
    # Selecting a real vendor keeps the line items unlocked.
    page.wait_for_selector('#lineItemsSection', state='visible')
