"""
Playwright e2e regression test for the shared search-select picker
(app/static/search-select.js::initSearchSelect).

BUG (confirmed): Choices.js reads each <option>'s innerHTML as its label. Jinja
autoescapes option text, so the <option> HTML carries entities (&amp; &lt; &gt;
&#34; &#39;). With allowHTML:false, Choices renders that escaped string as
PLAIN TEXT, so the entity shows LITERALLY in the dropdown and the selected
chip -- e.g. "O'Brien & <Sons> "Co."" renders as
"O&#39;Brien &amp; &lt;Sons&gt; &#34;Co.&#34;".

This affects every picker built on initSearchSelect (vendor picker here; also
customer/account pickers via the same function). Vendor V004 (seeded in
tests/e2e/_serve.py) carries every char Jinja escapes, specifically so this
test can assert on real DOM text the user actually sees.

RED (before fix): dropdown option text and/or the selected chip contain a
literal entity string (e.g. "&amp;") instead of the decoded character.
GREEN (after fix): both show the decoded characters and never the entities.
"""
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.accounts_payable]

AP_CREATE = '/accounts-payable/create'
VENDOR_SCOPE = '.choices:has(#payee)'

DECODED_NAME = 'O\'Brien & <Sons> "Co."'
ENTITY_FRAGMENTS = ['&amp;', '&lt;', '&gt;', '&#34;', '&#39;', '&quot;', '&apos;']


def test_vendor_picker_dropdown_shows_decoded_label(logged_in_page, e2e_server):
    """The dropdown OPTION for V004 must show the raw & < > " ' chars, never
    the escaped entity strings that Jinja put into the <option>'s innerHTML."""
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')

    scope = page.locator(VENDOR_SCOPE)
    scope.locator('.choices__inner').click()
    page.wait_for_selector(f'{VENDOR_SCOPE} .choices__list--dropdown .choices__item')

    option = scope.locator('.choices__list--dropdown .choices__item', has_text='V004').first
    option.wait_for(state='visible')
    text = option.inner_text()

    for frag in ENTITY_FRAGMENTS:
        assert frag not in text, (
            f'dropdown option for V004 contains a literal HTML entity {frag!r} '
            f'instead of the decoded character -- got: {text!r}'
        )
    assert "O'Brien" in text, f'expected decoded apostrophe in option text, got: {text!r}'
    assert '&' in text and '&amp;' not in text, f'expected decoded ampersand, got: {text!r}'
    assert '<Sons>' in text, f'expected decoded angle brackets, got: {text!r}'
    assert '"Co."' in text, f'expected decoded double quotes, got: {text!r}'


def test_vendor_picker_selected_chip_shows_decoded_label(logged_in_page, e2e_server):
    """After selecting V004, the chip that initSearchSelect manages (the
    Choices "single item" display) must also show the decoded label."""
    page = logged_in_page
    page.goto(e2e_server + AP_CREATE)
    page.wait_for_selector('#payee', state='attached')

    scope = page.locator(VENDOR_SCOPE)
    scope.locator('.choices__inner').click()
    scope.locator('.choices__list--dropdown .choices__item', has_text='V004').first.click()

    chip = scope.locator('.choices__list--single .choices__item')
    chip.wait_for(state='visible')
    text = chip.inner_text()

    for frag in ENTITY_FRAGMENTS:
        assert frag not in text, (
            f'selected vendor chip contains a literal HTML entity {frag!r} '
            f'instead of the decoded character -- got: {text!r}'
        )
    assert "O'Brien" in text and '<Sons>' in text and '"Co."' in text, \
        f'expected fully decoded vendor name in selected chip, got: {text!r}'
