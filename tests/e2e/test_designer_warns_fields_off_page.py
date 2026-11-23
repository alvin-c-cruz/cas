"""RICL-W A: the print designer warns about fields that are off the page, and marks them; nothing moves by itself.

Owner, typed in the root 23 Nov 2026 13:13: "RICL-W A". As put to him: when a smaller paper (or a saved layout) leaves
fields off the page, the designer lists them ("3 fields are off the page: Prepared by, Checked by, Approved by -- drag
them in") and outlines them in red, also when a saved layout opens. Nothing is moved for the user.

The check lives in the script every pre-printed print page and the cheque share (static/js/pp_paper.js, loaded by
templates/_pp_paper_extra.html), so it covers all eight designers at once. These tests drive the REAL rendered pages
(rendered by the Flask test client, loaded into the browser with the real JS and CSS over HTTP, as in
test_cd_check_print_page_boxed.py): the CDV voucher (the journal-entry designer shared with the APV) and the cheque.

Expected lists are literal, from the default layouts:
- CDV: the three signature texts sit at y=720; a 9.5 x 6.5 in paper is 624 px tall, so exactly those three are off.
  The line-item band is off by default; switched on, its Amount column (x 804 + width 100) fits the 912 px continuous
  paper but not Letter (816 px).
- PO (the shared PO/PR/RR designer), default layout: fits the 912 px continuous paper. On Letter (816 px) the
  right-hand fields' 200 px boxes start at x 620 and end at 820, and Total Amount (x 700, 150 px) ends at 850: a box
  past the edge widens what the browser prints, so each counts, though most are only 4 px over.
- Cheque, on an 8.5 in (816 px) paper: the boxed Date's digits reach 832 px (x 640, eight 24 px cells), Amount
  (Figures) 840 px (x 680 + width 160), Amount in Words 820 px (x 80 + width 740); Payee and Memo fit. Measured in
  the browser 23 Nov 2026. So the default cheque layout does not fit an 8.5 in wide paper as it stands.
"""
import functools
import http.server
import os
import socket
import threading

import pytest
from playwright.sync_api import expect

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import _cdv_with_je
from tests.integration.test_cd_check_print import _check_cdv
from tests.integration.test_print_paper_pages import _open
from tests.integration.test_p2p_preprinted_print import (p2p_modules_enabled, vendor_acme, approved_po,  # noqa: F401
                                                         _login)

pytestmark = [pytest.mark.e2e, pytest.mark.cash_disbursements]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RED = 'rgb(198, 40, 40)'
THREE_SIGNATURES = '3 fields are off the page: Prepared by, Checked by, Approved by — drag them in.'


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def static_server():
    handler = functools.partial(_QuietHandler, directory=os.path.join(PROJECT_ROOT, 'app'))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _show(page, static_server, html):
    page.route('**/*-layout*', lambda route: route.fulfill(status=200, content_type='application/json',
                                                           body='{"ok": true}'))
    page.route(static_server + '/', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(static_server + '/')


def _cdv_page(page, client, db_session, main_branch, static_server, **changes):
    """The CDV pre-printed voucher, with `changes` applied to its saved layout first (none: the default layout)."""
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    cdv = _cdv_with_je(db_session, main_branch)
    if changes:
        lay = get_layout(main_branch.id)
        for key, value in changes.items():
            if callable(value):
                value(lay)
            else:
                lay[key] = value
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    _open(client, main_branch)
    _show(page, static_server, client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True))


def _marked(page):
    """What carries the off-page mark, by the label a user reads."""
    return page.eval_on_selector_all(
        '#ppCanvas [data-pp-off]', 'els => els.map(e => e.dataset.label || e.dataset.el || e.dataset.col)')


def _positions(page):
    return page.eval_on_selector_all(
        '#ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol',
        'els => els.map(e => [e.dataset.el || e.dataset.text || e.dataset.col || e.dataset.jecol || e.dataset.je,'
        ' e.style.left, e.style.top])')


def _text(page, text_id):
    return page.locator(f'#ppCanvas [data-text="{text_id}"]')


def _enable_line_items(lay):
    lay['lineItems']['enabled'] = True


def _hide_approved_by(lay):
    for t in lay['texts']:
        if t['id'] == 'approved_by':
            t['hidden'] = True


SHORT_PAPER = {'paper': 'custom', 'paperSize': {'w': 9.5, 'h': 6.5}}


# --- A saved layout opens with its off-page fields listed and marked -------------------------------------------------

def test_a_saved_layout_opens_with_the_fields_off_the_page_listed(page, client, db_session, admin_user, main_branch,
                                                                  static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, **SHORT_PAPER)
    expect(page.locator('#ppOffPage')).to_be_visible()                  # on opening, before Edit Layout
    expect(page.locator('#ppOffPage')).to_have_text(THREE_SIGNATURES)
    assert _marked(page) == ['Prepared by:', 'Checked by:', 'Approved by:']


def test_the_off_page_fields_are_outlined_in_red(page, client, db_session, admin_user, main_branch, static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, **SHORT_PAPER)
    expect(page.locator('#ppOffPage')).to_have_text(THREE_SIGNATURES)
    for text_id in ('prepared_by', 'checked_by', 'approved_by'):
        style = _text(page, text_id).evaluate('e => [getComputedStyle(e).outlineStyle, getComputedStyle(e).outlineColor]')
        assert style == ['solid', RED], (text_id, style)
    # a field on the page keeps its own look
    assert page.locator('#ppCanvas [data-el="cdv_no"]').evaluate('e => getComputedStyle(e).outlineStyle') == 'none'


def test_nothing_is_listed_when_everything_fits(page, client, db_session, admin_user, main_branch, static_server):
    _cdv_page(page, client, db_session, main_branch, static_server)       # default layout, continuous paper
    page.click('#editLayoutBtn')
    page.wait_for_timeout(200)
    expect(page.locator('#ppOffPage')).to_be_hidden()
    assert _marked(page) == []


# --- A smaller paper: the warning follows the paper, and nothing moves ----------------------------------------------

def test_a_smaller_paper_lists_the_fields_it_leaves_off_and_moves_nothing(page, client, db_session, admin_user,
                                                                         main_branch, static_server):
    _cdv_page(page, client, db_session, main_branch, static_server)
    page.click('#editLayoutBtn')
    before = _positions(page)
    page.select_option('#ppPaper', 'custom')
    page.fill('#ppPaperW', '9.5')
    page.fill('#ppPaperH', '6.5')
    expect(page.locator('#ppOffPage')).to_have_text(THREE_SIGNATURES)
    assert _marked(page) == ['Prepared by:', 'Checked by:', 'Approved by:']
    assert _positions(page) == before, 'a field was moved for the user'
    # back to the full paper: the warning and the marks go
    page.select_option('#ppPaper', 'continuous')
    expect(page.locator('#ppOffPage')).to_be_hidden()
    assert _marked(page) == []
    assert _positions(page) == before


def test_a_line_item_column_past_the_edge_is_listed_as_a_column(page, client, db_session, admin_user, main_branch,
                                                               static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, lineItems=_enable_line_items)
    page.click('#editLayoutBtn')
    page.wait_for_timeout(200)
    expect(page.locator('#ppOffPage')).to_be_hidden()                  # 804 + 100 fits 912 px
    page.select_option('#ppPaper', 'letter')                            # 816 px
    expect(page.locator('#ppOffPage')).to_have_text('1 field is off the page: Amount column — drag it in.')
    assert _marked(page) == ['Amount']


# --- The user brings a field back; hidden fields do not count ---------------------------------------------------------

def test_dragging_a_field_back_onto_the_page_takes_it_off_the_list(page, client, db_session, admin_user, main_branch,
                                                                  static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, **SHORT_PAPER)
    page.click('#editLayoutBtn')
    box = _text(page, 'approved_by').bounding_box()
    page.mouse.move(box['x'] + 5, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.mouse.move(box['x'] + 5, box['y'] + box['height'] / 2 - 300, steps=6)
    page.mouse.up()
    expect(page.locator('#ppOffPage')).to_have_text(
        '2 fields are off the page: Prepared by, Checked by — drag them in.')
    assert _marked(page) == ['Prepared by:', 'Checked by:']


def test_a_hidden_field_off_the_page_is_not_listed(page, client, db_session, admin_user, main_branch, static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, texts=_hide_approved_by, **SHORT_PAPER)
    expect(page.locator('#ppOffPage')).to_have_text(
        '2 fields are off the page: Prepared by, Checked by — drag them in.')
    page.click('#editLayoutBtn')                                        # shown greyed while editing: still not listed
    page.wait_for_timeout(200)
    expect(page.locator('#ppOffPage')).to_have_text(
        '2 fields are off the page: Prepared by, Checked by — drag them in.')
    assert _marked(page) == ['Prepared by:', 'Checked by:']


# --- Never on paper ---------------------------------------------------------------------------------------------------

def test_the_warning_and_the_red_outline_never_print(page, client, db_session, admin_user, main_branch, static_server):
    _cdv_page(page, client, db_session, main_branch, static_server, **SHORT_PAPER)
    expect(page.locator('#ppOffPage')).to_have_text(THREE_SIGNATURES)
    page.emulate_media(media='print')
    expect(page.locator('#ppOffPage')).to_be_hidden()
    assert _text(page, 'approved_by').evaluate('e => getComputedStyle(e).outlineStyle') == 'none'


# --- The cheque designer gets the same warning ------------------------------------------------------------------------

def test_the_cheque_lists_the_fields_past_the_paper_edge(page, client, db_session, admin_user, main_branch, static_server):
    from app.cash_disbursements.check_layout import get_layout, save_layout
    cdv = _check_cdv(db_session, main_branch)
    lay = get_layout(cdv.cash_account_id)
    lay.update({'paper': 'custom', 'paperSize': {'w': 8.5, 'h': 3.5}})
    save_layout(lay, 'admin', cdv.cash_account_id)
    db_session.commit()
    _open(client, main_branch)
    _show(page, static_server, client.get(f'/cash-disbursements/{cdv.id}/print-check').get_data(as_text=True))
    expect(page.locator('#ppOffPage')).to_have_text(
        '3 fields are off the page: Date, Amount (Figures), Amount in Words — drag them in.')
    assert _marked(page) == ['Date', 'Amount (Figures)', 'Amount in Words']


# --- The shared PO / PR / RR designer -----------------------------------------------------------------------------------

def test_the_po_lists_the_fields_letter_paper_leaves_off(page, client, db_session, admin_user, branch_manila,
                                                         approved_po, static_server):
    AppSettings.set_setting('po_print_form', 'preprinted')
    db_session.commit()
    _login(client, admin_user, branch_manila)
    _show(page, static_server, client.get(f'/purchase-orders/{approved_po.id}/print').get_data(as_text=True))
    page.click('#editLayoutBtn')
    page.wait_for_timeout(200)
    expect(page.locator('#ppOffPage')).to_be_hidden()                  # the default layout fits continuous paper
    before = _positions(page)
    page.select_option('#ppPaper', 'letter')
    expect(page.locator('#ppOffPage')).to_have_text(
        '7 fields are off the page: PO No., Order Date, Expected Date, Terms, Reference, VAT Treatment, Total Amount'
        ' — drag them in.')
    assert _positions(page) == before, 'a field was moved for the user'
