"""Playwright e2e for the SI pre-printed layout designer (SI-P-71) — part 2.

Split from test_sv_preprinted_designer.py: the e2e dev server is module-scoped (one per
FILE) and progressively slows over many requests, so a single big file times out its later
tests. Two files -> two fresh servers -> each batch stays healthy. See tests/e2e/conftest.py.
"""
import re
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]


def _enable_preprinted(page, base):
    """Flip the company-wide Sales Invoice Print Form to 'Pre-printed Form'."""
    page.goto(base + '/settings')
    name = page.locator('#company_name')
    if (name.input_value() or '').strip() == '':
        name.fill('E2E Co')                     # company_name is required to save
    page.select_option('select[name="sv_print_form"]', 'preprinted')
    page.click('button:has-text("Save Settings")')
    page.wait_for_load_state('load')


def _first_si_print_url(page, base):
    page.goto(base + '/sales-invoices')
    hrefs = page.locator('a[href*="/sales-invoices/"]').evaluate_all(
        "els => els.map(e => e.getAttribute('href'))")
    for h in hrefs or []:
        m = re.search(r'/sales-invoices/(\d+)', h or '')
        if m:
            return f"{base}/sales-invoices/{m.group(1)}/print"
    raise AssertionError('no Sales Invoice id found on the list page')


def test_bold_and_page_font_persist(logged_in_page, e2e_server):
    # Runs FIRST: the shared module server persists layout saves, and test_duplicate
    # (below) saves an invoice_no copy that overlaps invoice_date; running bold before
    # that keeps invoice_date clickable.
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.click('[data-el="invoice_date"]')         # select a NON-bold field -> floating toolbar
    page.click('#ppBoldBtn')                       # toggle bold ON
    page.select_option('#ppFontFamily', 'Georgia, serif')   # page-wide font
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                 # fresh reload from the server
    weight = page.locator('[data-el="invoice_date"]').evaluate(
        "e => getComputedStyle(e).fontWeight")
    assert weight == '700' or weight == 'bold'     # per-element bold persisted
    fam = page.locator('body').evaluate("e => getComputedStyle(e).fontFamily")
    assert 'Georgia' in fam                         # page font-family persisted


def test_duplicate_field_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.click('[data-el="invoice_no"]')                     # select a field
    page.click('#ppDupBtn')                                   # duplicate it
    assert page.locator('[data-el="invoice_no"]').count() == 2
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    assert page.locator('[data-el="invoice_no"]').count() == 2
    assert page.locator('[data-el="invoice_no"][data-extra]').count() == 1


def test_signature_text_edit_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.click('[data-text="preparer"]')                     # select -> text box appears
    page.fill('#ppTextInput', 'Prepared by: Juan')           # edit the layout text
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    assert 'Juan' in page.locator('[data-text="preparer"]').inner_text()


def test_line_item_font_applies_to_band_and_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    amount = page.locator('.pp-col[data-col="amount"]')
    before = amount.evaluate("e => parseInt(getComputedStyle(e).fontSize)")
    amount.click()                                            # select the column
    page.click('#ppFontInc')
    page.click('#ppFontInc')
    after = amount.evaluate("e => parseInt(getComputedStyle(e).fontSize)")
    assert after > before
    qty = page.locator('.pp-col[data-col="quantity"]').evaluate("e => parseInt(getComputedStyle(e).fontSize)")
    assert qty == after                                       # applied to the whole band
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)
    persisted = page.locator('.pp-col[data-col="amount"]').evaluate("e => parseInt(getComputedStyle(e).fontSize)")
    assert persisted == after                                # persisted


def test_hide_field_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.uncheck('[data-fieldtoggle="terms"]')               # hide the Terms field
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    hidden = page.locator('[data-el="terms"]').evaluate(
        "e => e.classList.contains('pp-field-hidden')")
    assert hidden is True


# --- Phase 3: arbitrary text CRUD (texts dict->list). The designer JS is a shared
#     clone, so exercising it here covers the identical CRV/APV code path. ---

def test_add_text_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    before = page.locator('.pp-text').count()
    page.click('#addTextBtn')                                # add a fresh layout text
    assert page.locator('.pp-text').count() == before + 1
    page.fill('#ppTextInput', 'Subject to 2% EWT')           # edit its content (it's selected)
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload from server
    assert page.locator('.pp-text').count() == before + 1    # added text survived
    texts = page.locator('.pp-text').evaluate_all("els => els.map(e => e.textContent)")
    assert any('EWT' in (t or '') for t in texts)


def test_delete_signatory_warns_and_stays_gone(logged_in_page, e2e_server):
    # Runs LAST: it removes the 'checker' signatory permanently on the shared server.
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.click('[data-text="checker"]')                      # select a pre-printed signatory
    page.click('#ppDelBtn')                                   # delete it
    assert page.locator('#ppNotice').is_visible()            # non-blocking warning (no confirm())
    assert page.locator('[data-text="checker"]').count() == 0
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    assert page.locator('[data-text="checker"]').count() == 0  # stays deleted (not re-injected)
