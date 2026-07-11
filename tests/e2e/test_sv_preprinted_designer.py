"""Playwright e2e for the SI pre-printed layout designer (SI-P-71) — the drag layer.

The e2e server runs in its own subprocess DB, so persistence is verified by RELOADING
the print page and reading the server-rendered positions/columns/fonts from the DOM
(not by reading the DB). CSRF is ON in the e2e server; the save fetch sends the
X-CSRFToken from the <meta> tag.
"""
import re
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]


def _enable_preprinted(page, base):
    """Flip the company-wide Sales Invoice Print Form to 'Pre-printed Form'."""
    page.goto(base + '/settings')
    name = page.locator('#company_name')
    if (name.input_value() or '').strip() == '':
        name.fill('E2E Co')                     # company_name is required to save (Company Profile tab, active by default)
    # Print Form now lives in the "Documents & Print" tab (settings tabbed makeover) — the select
    # is display:none until its tab is active, so activate it before select_option.
    page.click('.tab[data-tab-group="settings"][data-tab="docprint"]')
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


def test_drag_persists_after_save_and_reload(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')                 # enter edit mode
    el = page.locator('[data-el="invoice_no"]')
    box = el.bounding_box()
    page.mouse.move(box['x'] + 10, box['y'] + 8)
    page.mouse.down()
    page.mouse.move(box['x'] + 130, box['y'] + 70, steps=10)
    page.mouse.up()
    before_left = el.evaluate("e => parseInt(e.style.left)")
    assert before_left is not None
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                               # fresh reload from the server
    after_left = page.locator('[data-el="invoice_no"]').evaluate("e => parseInt(e.style.left)")
    assert abs(after_left - before_left) <= 2    # dragged position persisted


def test_hide_column_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.uncheck('[data-coltoggle="uom"]')       # hide the UOM column
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                               # fresh reload from the server
    # UOM column still in the DOM but marked hidden; a visible column is not.
    uom_hidden = page.locator('.pp-col[data-col="uom"]').evaluate(
        "e => e.classList.contains('pp-col-hidden')")
    amount_hidden = page.locator('.pp-col[data-col="amount"]').evaluate(
        "e => e.classList.contains('pp-col-hidden')")
    assert uom_hidden is True
    assert amount_hidden is False


def test_column_horizontal_drag_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    col = page.locator('.pp-col[data-col="amount"]')
    box = col.bounding_box()
    before_x = col.evaluate("e => parseInt(e.style.left)")
    page.mouse.move(box['x'] + 8, box['y'] + 8)
    page.mouse.down()
    page.mouse.move(box['x'] - 90, box['y'] + 8, steps=10)   # drag the column left
    page.mouse.up()
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    after_x = page.locator('.pp-col[data-col="amount"]').evaluate("e => parseInt(e.style.left)")
    assert after_x < before_x                                 # column moved left, persisted


def test_column_width_resize_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    col = page.locator('.pp-col[data-col="product"]')
    box = col.bounding_box()
    before_w = col.evaluate("e => parseInt(e.style.width)")
    # grab the right edge and drag left to shrink the column
    page.mouse.move(box['x'] + box['width'] - 2, box['y'] + 6)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] - 90, box['y'] + 6, steps=10)
    page.mouse.up()
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    after_w = page.locator('.pp-col[data-col="product"]').evaluate("e => parseInt(e.style.width)")
    assert after_w < before_w                                 # narrower width persisted


def test_paper_change_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.select_option('#ppPaper', 'letter')                 # switch to Letter 8.5x11
    # canvas resized live
    assert page.locator('#ppCanvas').evaluate("e => e.style.width") == '816px'
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    assert page.locator('body').evaluate("e => e.dataset.paper") == 'letter'
    assert page.locator('#ppCanvas').evaluate("e => e.style.width") == '816px'


def test_date_format_change_persists(logged_in_page, e2e_server):
    page = logged_in_page
    _enable_preprinted(page, e2e_server)
    url = _first_si_print_url(page, e2e_server)
    page.goto(url)
    page.click('#editLayoutBtn')
    page.select_option('#ppDateFormat', 'iso')                # switch to YYYY-MM-DD
    assert page.locator('[data-el="invoice_date"]').inner_text().count('-') == 2  # live preview
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)                                            # fresh reload
    assert page.locator('[data-el="invoice_date"]').inner_text().count('-') == 2  # persisted
