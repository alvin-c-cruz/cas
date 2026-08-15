"""Playwright e2e for the SHARED pre-printed layout designer (app/static/js/preprinted_designer.js).

Unlike the per-document designer e2e files (test_sv_preprinted_designer*.py), this one
does not need the Flask app: the shared designer is browser-only, and the first real
page that loads it does not exist yet (it arrives with the P2P print templates). So the
suite serves a static stand-in page -- tests/e2e/_preprinted_designer_harness.html --
over plain HTTP from the repo root and drives the real JS file against it.

HTTP (not file://) on purpose: the save POST must be a same-origin request so it can be
intercepted with `page.route` and inspected. The harness's saveUrl is a made-up path
('/pp-test-save'), so a designer that ignored its config and POSTed a hardcoded document
URL would miss the route, hit the static server's 404 and fail these tests.
"""
import functools
import http.server
import json
import os
import socket
import threading
import urllib.parse

import pytest

pytestmark = [pytest.mark.e2e]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

SAVE_PATH = '/pp-test-save'          # the configured endpoint; nothing in app/ uses it
SAFE_MARGIN = 48                     # app/common/preprinted_base.py
CANVAS_W, CANVAS_H = 912, 1008


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):    # keep pytest output clean
        pass


@pytest.fixture(scope='module')
def static_server():
    """Serve the repo root over HTTP so the harness can load the real JS/CSS files."""
    handler = functools.partial(_QuietHandler, directory=PROJECT_ROOT)
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
def harness_url(static_server):
    return static_server + '/tests/e2e/_preprinted_designer_harness.html'


@pytest.fixture
def designer(page, harness_url):
    """Harness page with the shared designer initialised, edit mode OFF."""
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(harness_url)
    started = page.evaluate(
        "url => initPreprintedDesigner({ saveUrl: url })", SAVE_PATH)
    assert started is True, 'initPreprintedDesigner did not initialise'
    return page


def _drag_to(page, selector, to_x, to_y, grab=(0.5, 0.5)):
    """Press the element (at `grab`, a fraction of its box) and drag to viewport (to_x, to_y).

    The grab point matters: the designer positions by the element's LEFT/TOP, so the
    pointer can only push the left edge as far right as (pointer_x - grab offset).
    Grabbing a 500px-wide field by its centre cannot reach the right clamp at all.
    """
    box = page.locator(selector).bounding_box()
    page.mouse.move(box['x'] + box['width'] * grab[0], box['y'] + box['height'] * grab[1])
    page.mouse.down()
    page.mouse.move(to_x, to_y, steps=6)
    page.mouse.up()


def _left_top(page, selector):
    return page.locator(selector).evaluate(
        "e => [parseInt(e.style.left), parseInt(e.style.top)]")


def _intercept_save(page):
    """Route the configured save endpoint and record what the designer POSTs."""
    captured = {}

    def handler(route, request):
        captured['url'] = request.url
        captured['method'] = request.method
        captured['headers'] = request.headers
        captured['body'] = request.post_data
        route.fulfill(status=200, content_type='application/json', body='{"ok": true}')

    page.route('**' + SAVE_PATH, handler)
    return captured


# --- clamping -------------------------------------------------------------------

def test_field_dragged_past_left_edge_clamps_at_safe_margin(designer):
    """A field stops at the printable inset (48), NOT at the canvas edge (0).

    The server sanitiser clamps a field's x to SAFE_MARGIN..CANVAS_W-SAFE_MARGIN, so a
    designer that clamped at 0 would let a user place a field where it silently jumps on
    the next page load.
    """
    page = designer
    page.click('#editLayoutBtn')
    canvas = page.locator('#ppCanvas').bounding_box()
    assert canvas['x'] > 60, 'harness canvas needs room to its left to drag past the edge'
    _drag_to(page, '[data-el="po_no"]', 2, canvas['y'] + 40)
    left, _top = _left_top(page, '[data-el="po_no"]')
    assert left == SAFE_MARGIN


def test_field_dragged_past_right_and_bottom_clamps_inside_canvas(designer):
    page = designer
    page.click('#editLayoutBtn')
    _drag_to(page, '[data-el="vendor_name"]', 1278, 1198, grab=(0.02, 0.5))
    left, top = _left_top(page, '[data-el="vendor_name"]')
    assert left == CANVAS_W - SAFE_MARGIN     # 864
    assert top == CANVAS_H                    # 1008
    assert left < CANVAS_W and top <= CANVAS_H


def test_drag_within_bounds_is_not_clamped(designer):
    """Control: the clamps must not pin every drag -- an in-bounds move still lands."""
    page = designer
    page.click('#editLayoutBtn')
    canvas = page.locator('#ppCanvas').bounding_box()
    _drag_to(page, '[data-el="po_no"]', canvas['x'] + 400, canvas['y'] + 500)
    left, top = _left_top(page, '[data-el="po_no"]')
    assert SAFE_MARGIN < left < CANVAS_W - SAFE_MARGIN
    assert 0 < top < CANVAS_H


# --- font size band -------------------------------------------------------------

def _font_size(page, selector):
    return page.locator(selector).evaluate("e => parseInt(getComputedStyle(e).fontSize)")


def test_font_decrease_stops_at_6px(designer):
    page = designer
    page.click('#editLayoutBtn')
    page.locator('[data-el="po_no"]').evaluate("e => { e.style.fontSize = '7px'; }")
    page.click('[data-el="po_no"]')
    page.click('#ppFontDec')
    assert _font_size(page, '[data-el="po_no"]') == 6      # 7 -> 6
    page.click('#ppFontDec')
    assert _font_size(page, '[data-el="po_no"]') == 6      # floor holds


def test_font_increase_stops_at_72px(designer):
    page = designer
    page.click('#editLayoutBtn')
    page.locator('[data-el="po_no"]').evaluate("e => { e.style.fontSize = '71px'; }")
    page.click('[data-el="po_no"]')
    page.click('#ppFontInc')
    assert _font_size(page, '[data-el="po_no"]') == 72     # 71 -> 72
    page.click('#ppFontInc')
    assert _font_size(page, '[data-el="po_no"]') == 72     # ceiling holds


# --- bold -----------------------------------------------------------------------

def test_bold_toggles_rendered_font_weight(designer):
    page = designer
    page.click('#editLayoutBtn')
    weight = page.locator('[data-el="order_date"]').evaluate(
        "e => getComputedStyle(e).fontWeight")
    assert weight in ('400', 'normal')                      # starts non-bold
    page.click('[data-el="order_date"]')
    page.click('#ppBoldBtn')
    assert page.locator('[data-el="order_date"]').evaluate(
        "e => getComputedStyle(e).fontWeight") in ('700', 'bold')
    page.click('#ppBoldBtn')                                # toggles back off
    assert page.locator('[data-el="order_date"]').evaluate(
        "e => getComputedStyle(e).fontWeight") in ('400', 'normal')


# --- save ------------------------------------------------------------------------

def test_save_posts_expected_payload_to_the_configured_url(designer):
    page = designer
    captured = _intercept_save(page)
    page.click('#editLayoutBtn')
    canvas = page.locator('#ppCanvas').bounding_box()
    _drag_to(page, '[data-el="po_no"]', 2, canvas['y'] + 40)   # -> x clamps to 48
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)

    # reached the CONFIGURED endpoint, not a hardcoded document URL
    assert urllib.parse.urlparse(captured['url']).path == SAVE_PATH
    assert captured['method'] == 'POST'
    assert 'application/json' in captured['headers']['content-type']
    assert captured['headers']['x-csrftoken'] == 'harness-csrf-token'

    payload = json.loads(captured['body'])
    assert set(payload) == {'paper', 'dateFormat', 'extras', 'texts',
                            'page', 'fields', 'lineItems'}
    assert payload['paper'] == 'continuous'
    assert payload['dateFormat'] == 'long'
    assert payload['page']['fontFamily'].startswith('"Courier New"')

    po = payload['fields']['po_no']
    assert set(po) == {'x', 'y', 'w', 'fontSize', 'bold', 'hidden'}
    assert po['x'] == SAFE_MARGIN                  # the dragged (clamped) position
    assert 0 <= po['y'] <= CANVAS_H
    assert (po['w'], po['fontSize'], po['bold'], po['hidden']) == (200, 12, True, False)
    assert set(payload['fields']) == {'vendor_name', 'po_no', 'order_date'}

    assert payload['extras'] == []
    assert payload['texts'] == [{'id': 'preparer', 'text': 'Preparer', 'x': 60,
                                 'y': 720, 'fontSize': 10, 'bold': False,
                                 'hidden': False}]

    li = payload['lineItems']
    assert li['y'] == 300 and li['rowHeight'] == 20 and li['fontSize'] == 10
    assert li['bold'] is False
    assert li['columns'] == [
        {'key': 'product', 'x': 120, 'visible': True, 'width': 260},
        {'key': 'amount', 'x': 700, 'visible': True, 'width': 120},
    ]


def test_hidden_field_and_hidden_column_reach_the_payload(designer):
    page = designer
    captured = _intercept_save(page)
    page.click('#editLayoutBtn')
    page.uncheck('[data-fieldtoggle="order_date"]')
    page.uncheck('[data-coltoggle="amount"]')
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    payload = json.loads(captured['body'])
    assert payload['fields']['order_date']['hidden'] is True
    assert payload['fields']['po_no']['hidden'] is False          # control
    cols = {c['key']: c['visible'] for c in payload['lineItems']['columns']}
    assert cols == {'product': True, 'amount': False}


def test_save_failure_shows_a_notice_and_no_saved_flag(designer):
    """A rejected save must not look like a successful one (and never via alert())."""
    page = designer
    page.route('**' + SAVE_PATH, lambda route, request: route.fulfill(
        status=403, content_type='application/json',
        body='{"error": "Layout is locked for this branch."}'))
    page.click('#editLayoutBtn')
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#ppNotice', state='visible', timeout=5000)
    assert 'Layout is locked' in page.locator('#ppNotice').inner_text()
    assert page.locator('#layoutSavedFlag').count() == 0


def test_missing_save_url_refuses_to_initialise(page, harness_url):
    """Fail closed: no saveUrl -> no designer at all, rather than an unsaveable one."""
    page.goto(harness_url)
    started = page.evaluate("() => initPreprintedDesigner({})")
    assert started is False
    assert page.locator('#saveLayoutBtn').count() == 0
    page.click('#editLayoutBtn')
    assert page.locator('#ppCanvas').evaluate(
        "e => e.classList.contains('pp-editing')") is False


# --- edit mode off ---------------------------------------------------------------

def test_edit_mode_off_carries_no_editing_affordances(designer):
    page = designer
    assert page.locator('#ppCanvas').evaluate(
        "e => e.classList.contains('pp-editing')") is False
    assert page.locator('#saveLayoutBtn').is_visible() is False
    assert page.locator('#addTextBtn').is_visible() is False
    assert page.locator('#ppFieldControls').is_visible() is False
    assert page.locator('#ppColControls').is_visible() is False
    assert page.locator('#ppElemBar').is_visible() is False
    before = _left_top(page, '[data-el="po_no"]')
    _drag_to(page, '[data-el="po_no"]', 2, 300)               # drag is inert
    assert _left_top(page, '[data-el="po_no"]') == before
    assert page.locator('.pp-selected').count() == 0
