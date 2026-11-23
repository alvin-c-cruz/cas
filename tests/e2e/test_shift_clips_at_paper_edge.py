"""SHIFT-SCALE: a page shift moves the print on the paper and never changes its scale; what passes the edge is cut off.

Work order 2026-11-23-page-shift-shrinks-print.md. Philgen's PO layout "Manila" with "Shift whole page" X +9.5 / Y +2.8 mm
printed about 4% small (measured 0.965 across, 0.954 down). The shift was a print-only translate of the whole canvas,
which is exactly the paper's size, so the moved canvas reached 9.5 mm past the paper and the browser shrank the page to
fit (215.9 / 225.4 = 0.958). Nothing clipped at the paper edge, so a FIELD placed past the edge did the same.

Now, in print only: the canvas clips at the paper's edge, and the shift moves the fields inside it (the CSS `translate`
property on each placed element), not the canvas. The root's instruction, 23 Nov 2026 ~14:20, to build it locally.

These tests render the real pages through the Flask test client and load them into Edge with the real JS and CSS (as in
test_cd_check_print_page_boxed.py). "No wider than the paper" is read with the viewport set to the paper's width: any
content past it makes the document wider, which is what the browser shrinks to fit when printing. One test also prints
a PDF and reads where a field landed.
"""
import functools
import http.server
import io
import os
import re
import socket
import threading

import pytest

from app.settings import AppSettings
from tests.integration.test_cd_check_print import _check_cdv
from tests.integration.test_cdv_print_form import _cdv_with_je
from tests.integration.test_print_paper_pages import _open

pytestmark = [pytest.mark.e2e, pytest.mark.cash_disbursements]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PX_PER_MM = 96 / 25.4
SHIFT = {'x': 9.5, 'y': 2.8}                 # Philgen's PO "Manila" calibration (CAL-1 A)
RULE = ('@media print { #ppCanvas { overflow: hidden; } '
        '#ppCanvas .pp-el, #ppCanvas .pp-col, #ppCanvas .pp-jecol { translate: 9.5mm 2.8mm; } }')
FIELDS = ('[data-el="cdv_no"]', '[data-text="prepared_by"]')


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


@pytest.fixture
def cdv(client, db_session, admin_user, main_branch):
    """A CDV on the pre-printed form; the layout is changed per test with _relayout()."""
    voucher = _cdv_with_je(db_session, main_branch)
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    _open(client, main_branch)
    return voucher


def _relayout(db_session, branch_id, change):
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    lay = get_layout(branch_id)
    change(lay)
    save_layout(lay, 'admin', branch_id)
    db_session.commit()


def _shift(x, y):
    def change(lay):
        lay['offset'] = {'x': x, 'y': y}
    return change


def _show(page, static_server, html, width):
    page.route('**/*-layout*', lambda route: route.fulfill(status=200, content_type='application/json',
                                                           body='{"ok": true}'))
    page.route(static_server + '/', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(static_server + '/')


def _cdv_page(page, client, static_server, voucher, width):
    html = client.get(f'/cash-disbursements/{voucher.id}/print').get_data(as_text=True)
    _show(page, static_server, html, width)
    return html


def _printed_width(page):
    page.emulate_media(media='print')
    return page.evaluate('() => document.documentElement.scrollWidth')


def _boxes(page):
    return {sel: page.locator('#ppCanvas ' + sel).evaluate(
        'e => { const r = e.getBoundingClientRect(); return [r.left, r.top]; }') for sel in FIELDS}


# --- The page stays the paper's size ---------------------------------------------------------------------------------

def test_a_shifted_page_prints_no_wider_than_the_paper(page, client, db_session, main_branch, cdv, static_server):
    _relayout(db_session, main_branch.id, _shift(**SHIFT))
    _cdv_page(page, client, static_server, cdv, 912)          # continuous paper, 9.5 in = 912 px
    assert _printed_width(page) == 912


def test_a_field_past_the_edge_does_not_widen_the_printed_page(page, client, db_session, main_branch, cdv,
                                                               static_server):
    def far_right(lay):
        lay['fields']['cdv_no']['x'] = 864                    # the furthest a field may be placed (912 - 48)
    _relayout(db_session, main_branch.id, far_right)
    _cdv_page(page, client, static_server, cdv, 912)
    assert page.evaluate("""() => document.querySelector('#ppCanvas [data-el="cdv_no"]').getBoundingClientRect().right
                                  - document.getElementById('ppCanvas').getBoundingClientRect().left""") > 912
    assert _printed_width(page) == 912


def test_the_cheque_too(page, client, db_session, admin_user, main_branch, static_server):
    from app.cash_disbursements.check_layout import get_layout, save_layout
    voucher = _check_cdv(db_session, main_branch)
    lay = get_layout(voucher.cash_account_id)
    lay['offset'] = SHIFT
    save_layout(lay, 'admin', voucher.cash_account_id)
    db_session.commit()
    _open(client, main_branch)
    _show(page, static_server, client.get(f'/cash-disbursements/{voucher.id}/print-check').get_data(as_text=True),
          912)
    assert _printed_width(page) == 912


# --- The fields move by exactly the shift, on paper only ---------------------------------------------------------------

def test_the_fields_move_by_the_shift_on_paper_only(page, client, db_session, main_branch, cdv, static_server):
    _cdv_page(page, client, static_server, cdv, 1280)
    page.emulate_media(media='print')
    still = _boxes(page)

    _relayout(db_session, main_branch.id, _shift(**SHIFT))
    _cdv_page(page, client, static_server, cdv, 1280)
    page.emulate_media(media='screen')
    on_screen = _boxes(page)
    page.emulate_media(media='print')
    for sel, (x1, y1) in _boxes(page).items():
        x0, y0 = still[sel]
        assert abs((x1 - x0) - 9.5 * PX_PER_MM) < 0.5 and abs((y1 - y0) - 2.8 * PX_PER_MM) < 0.5, (sel, x1 - x0, y1 - y0)
    page.emulate_media(media='screen')
    assert _boxes(page) == on_screen                          # the designer's screen keeps its geometry


# --- The live rule matches the saved one -------------------------------------------------------------------------------

def test_typing_a_shift_writes_the_same_rule_the_page_prints_with(page, client, db_session, main_branch, cdv,
                                                                  static_server):
    _relayout(db_session, main_branch.id, _shift(**SHIFT))
    saved = client.get(f'/cash-disbursements/{cdv.id}/print').get_data(as_text=True)
    assert re.search(r'<style id="ppShiftStyle">(.*?)</style>', saved, re.S).group(1) == RULE
    _relayout(db_session, main_branch.id, _shift(0, 0))
    _cdv_page(page, client, static_server, cdv, 1280)
    page.click('#editLayoutBtn')
    page.fill('#ppShiftX', '9.5')
    page.fill('#ppShiftY', '2.8')
    assert page.locator('#ppShiftStyle').text_content() == RULE


# --- On paper: a PDF printed by the browser ----------------------------------------------------------------------------

def test_the_printed_pdf_has_one_page_and_the_field_where_it_was_put(page, client, db_session, main_branch, cdv,
                                                                    static_server):
    from pypdf import PdfReader
    _relayout(db_session, main_branch.id, _shift(**SHIFT))
    _cdv_page(page, client, static_server, cdv, 912)
    pdf = PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True)))
    assert len(pdf.pages) == 1                                # the Y shift spills nothing onto a second sheet
    found = []

    def visit(text, cm, tm, font, size):
        if text.strip().startswith('CDV-PP-1'):
            found.append(cm[0] * tm[4] + cm[2] * tm[5] + cm[4])
    pdf.pages[0].extract_text(visitor_text=visit)
    assert found, 'CDV No. not found in the PDF'
    # cdv_no is placed at x 520 px = 390 pt; plus 9.5 mm = 26.93 pt: at full scale it lands at 416.9 pt.
    assert abs(found[0] - (390 + 9.5 * 72 / 25.4)) < 1.5, found
