"""Playwright e2e for the SI pre-printed designer — part 3: the legacy-invoice controls
(owner, 3 Nov 2026). Right-justified field boxes, a column's row offset, the end marker and
the MM-DD-YYYY date. Own file -> own module-scoped server (see test_sv_preprinted_designer_b.py).
Persistence is checked by reloading the print page and reading the server-rendered DOM.
"""
import re

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.sales_invoices]


def _enable_preprinted(page, base):
    page.goto(base + '/settings')
    name = page.locator('#company_name')
    if (name.input_value() or '').strip() == '':
        name.fill('E2E Co')
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


def _save_and_reload(page, url):
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    page.goto(url)


def _open_designer(page, base):
    _enable_preprinted(page, base)
    url = _first_si_print_url(page, base)
    page.goto(url)
    page.click('#editLayoutBtn')
    return url


def test_field_justified_right_in_a_box_persists(logged_in_page, e2e_server):
    page = logged_in_page
    url = _open_designer(page, e2e_server)
    page.click('[data-el="gross_sales"]:not([data-extra])')
    page.click('#ppAlignBtn')
    assert page.locator('#ppAlignBtn').inner_text() == 'Right'
    page.fill('#ppWidthInput', '150')
    _save_and_reload(page, url)
    style = page.locator('[data-el="gross_sales"]:not([data-extra])').evaluate(
        "e => [e.style.textAlign, e.style.width]")
    assert style == ['right', '150px']


def test_column_row_offset_persists(logged_in_page, e2e_server):
    page = logged_in_page
    url = _open_designer(page, e2e_server)
    col = page.locator('.pp-col[data-col="amount"]')
    box = col.bounding_box()
    page.mouse.click(box['x'] + 6, box['y'] + 4)            # select (away from the resize edge)
    page.fill('#ppDyInput', '12')
    _save_and_reload(page, url)
    vals = page.locator('.pp-col').evaluate_all(
        "els => els.map(e => [e.dataset.col, parseInt(e.dataset.dy) || 0, parseInt(e.style.top)])")
    by = {k: (dy, top) for k, dy, top in vals}
    assert by['amount'][0] == 12
    assert by['amount'][1] == by['product'][1] + 12          # the others keep the band top


def test_end_marker_switched_on_with_new_text_persists(logged_in_page, e2e_server):
    page = logged_in_page
    url = _open_designer(page, e2e_server)
    page.check('input[data-coltoggle="endMarker"]')
    page.click('.pp-endmark')
    page.fill('#ppTextInput', '**NOTHING FOLLOWS**')
    _save_and_reload(page, url)
    em = page.locator('.pp-endmark')
    assert 'pp-field-hidden' not in (em.get_attribute('class') or '')
    assert em.inner_text().strip() == '**NOTHING FOLLOWS**'


def test_dashed_date_previews_live(logged_in_page, e2e_server):
    page = logged_in_page
    _open_designer(page, e2e_server)
    page.select_option('#ppDateFormat', 'us_dash')
    text = page.locator('[data-el="invoice_date"]:not([data-extra])').inner_text().strip()
    assert re.fullmatch(r'\d{2}-\d{2}-\d{4}', text), text
