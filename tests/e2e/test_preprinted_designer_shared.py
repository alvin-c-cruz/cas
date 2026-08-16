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
COL_WIDTH_MIN = 20                   # app/static/js/preprinted_designer.js
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


def _drag_from(page, from_x, from_y, to_x, to_y):
    """Press an exact viewport point and drag to another -- for the column resize
    handle, which is only the 8px hot-zone at a column's right edge."""
    page.mouse.move(from_x, from_y)
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


# --- y clamps at the CONSTANT 1008, not at the live canvas height -----------------
#
# On continuous stock the canvas IS 1008px tall, so the two are indistinguishable --
# every clamp test above passes either way. Letter is what separates them: the canvas
# becomes 816 x 1056 (preprinted_base.PAPER_SIZES) while `_clean_box` keeps clamping y
# to CANVAS_H = 1008. The shipped clampY read `canvas.clientHeight`, so on Letter a
# field could be dragged to y=1050, look right, save, and come back at 1008 on the next
# load -- a silent 42px upward jump. That is the same defect class the x-axis fix
# (7c7dfd1d) removed; it was simply still live on y.
#
# `LETTER_H` is asserted from the harness's own <option data-h>, not typed in twice, so
# these tests cannot go vacuous by drifting away from the paper table they exist to
# straddle.
LETTER_H = 1056        # preprinted_base.PAPER_SIZES['letter']['h']
LETTER_W = 816


def _select_letter(page):
    """Switch the harness to Letter and confirm the canvas really grew past CANVAS_H.

    Without this check a designer that ignored the paper <select> entirely would leave
    the canvas at 1008 and the clamp assertions below would pass for the wrong reason.
    """
    page.select_option('#ppPaper', 'letter')
    size = page.locator('#ppCanvas').evaluate(
        "e => [e.clientWidth, e.clientHeight]")
    assert size == [LETTER_W, LETTER_H], \
        f'the harness did not switch to Letter: canvas is {size}'
    assert LETTER_H > CANVAS_H, 'Letter must be TALLER than CANVAS_H or this proves nothing'
    return page.locator('#ppCanvas').bounding_box()


def test_field_on_letter_clamps_y_at_canvas_h_not_at_the_taller_canvas(designer):
    """Drag a field to y=1050 on Letter: it must stop at 1008, the server's ceiling."""
    page = designer
    page.set_viewport_size({'width': 1280, 'height': 1400})
    page.click('#editLayoutBtn')
    canvas = _select_letter(page)

    _drag_to(page, '[data-el="po_no"]', canvas['x'] + 200, canvas['y'] + 1050)
    _left, top = _left_top(page, '[data-el="po_no"]')
    assert top == CANVAS_H, \
        f'y clamped to {top}; the server would store 1008 and the field would jump'
    assert top < LETTER_H


def test_line_item_band_on_letter_clamps_y_at_canvas_h(designer):
    """lineItems.y shares clampY, and the band carries every row with it -- an
    unclamped band means the whole table jumps on reload, not one field."""
    page = designer
    page.set_viewport_size({'width': 1280, 'height': 1400})
    page.click('#editLayoutBtn')
    canvas = _select_letter(page)

    box = page.locator(PRODUCT_COL).bounding_box()
    _drag_to(page, PRODUCT_COL, box['x'] + box['width'] / 2, canvas['y'] + 1050)
    assert _left_top(page, PRODUCT_COL)[1] == CANVAS_H
    assert _left_top(page, AMOUNT_COL)[1] == CANVAS_H, 'the band split'


def test_text_block_on_letter_clamps_y_at_canvas_h(designer):
    """The third caller of clampY: a .pp-text signatory block."""
    page = designer
    page.set_viewport_size({'width': 1280, 'height': 1400})
    page.click('#editLayoutBtn')
    canvas = _select_letter(page)

    _drag_to(page, '.pp-text[data-text="preparer"]',
             canvas['x'] + 200, canvas['y'] + 1050)
    _left, top = _left_top(page, '.pp-text[data-text="preparer"]')
    assert top == CANVAS_H


def test_a_letter_drag_above_canvas_h_is_not_clamped(designer):
    """Control: clamping at the CONSTANT must not pin every Letter drag to 1008.

    Without this, `return CANVAS_H` would satisfy all three tests above."""
    page = designer
    page.set_viewport_size({'width': 1280, 'height': 1400})
    page.click('#editLayoutBtn')
    canvas = _select_letter(page)

    _drag_to(page, '[data-el="po_no"]', canvas['x'] + 200, canvas['y'] + 900)
    _left, top = _left_top(page, '[data-el="po_no"]')
    assert 800 < top < CANVAS_H


def test_the_clamped_letter_y_is_what_reaches_the_save_payload(designer):
    """The DOM assertions above are only as good as what collect() sends: the whole
    point is that the SERVER never has to correct the number."""
    page = designer
    page.set_viewport_size({'width': 1280, 'height': 1400})
    captured = _intercept_save(page)
    page.click('#editLayoutBtn')
    canvas = _select_letter(page)
    _drag_to(page, '[data-el="po_no"]', canvas['x'] + 200, canvas['y'] + 1050)

    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)
    payload = json.loads(captured['body'])
    assert payload['paper'] == 'letter'
    assert payload['fields']['po_no']['y'] == CANVAS_H


# --- column drag: columns clamp EXACTLY like fields -------------------------------
#
# These two tests were written one commit ago to pin the OPPOSITE behaviour: a column
# clamped to the bare canvas (0..912) while a field clamped to the printable inset
# (48..864), so a user could drag a column onto the tractor-feed perforations and the
# server would persist it there. The owner removed that asymmetry on 2026-08-15 by
# tightening the SERVER's _clean_columns (and its declaration validator) to the field
# bound, mirrored here in clampColX. These tests are therefore INVERTED, not deleted --
# the pairing is kept so the new SYMMETRY is pinned exactly as deliberately as the old
# asymmetry was, and a later editor cannot quietly restore either one with a green suite.

PRODUCT_COL = '.pp-col[data-col="product"]'
AMOUNT_COL = '.pp-col[data-col="amount"]'


def test_column_clamps_at_the_safe_margin_exactly_like_a_field(designer):
    """The symmetry, pinned from BOTH sides so neither clamp can be swapped.

    A line-item COLUMN may NOT sit flush at x=0 any more: it stops at SAFE_MARGIN,
    exactly where a FIELD stops (_clean_columns and _clean_box now share one bound).
    Dragging both to the SAME viewport point must therefore land them on the SAME x.
    If clampColX were reverted to the bare canvas the column would reach 0 and then
    silently jump to 48 on reload -- the defect this change removed.
    """
    page = designer
    page.click('#editLayoutBtn')
    canvas = page.locator('#ppCanvas').bounding_box()
    assert canvas['x'] > 60, 'harness canvas needs room to its left to drag past the edge'
    target = (2, canvas['y'] + 320)

    _drag_to(page, PRODUCT_COL, *target)
    col_left, _col_top = _left_top(page, PRODUCT_COL)

    _drag_to(page, '[data-el="po_no"]', *target)
    field_left, _field_top = _left_top(page, '[data-el="po_no"]')

    assert col_left == SAFE_MARGIN        # a column clamps inside the printable inset
    assert field_left == SAFE_MARGIN      # ... and so does a field
    assert col_left == field_left         # ... i.e. it is ONE clamp, not two


def test_column_dragged_past_the_right_edge_clamps_inside_the_canvas(designer):
    """The other end of the same bound: a column stops at CANVAS_W - SAFE_MARGIN (864),
    not at the canvas edge (912), so it can never be stored on the right perforations."""
    page = designer
    page.click('#editLayoutBtn')
    _drag_to(page, PRODUCT_COL, 1278, 1198, grab=(0.02, 0.5))
    left, top = _left_top(page, PRODUCT_COL)
    assert left == CANVAS_W - SAFE_MARGIN     # 864
    assert left < CANVAS_W
    assert top <= CANVAS_H


def test_column_drag_within_bounds_is_not_clamped(designer):
    """Control: clampColX must not pin every column drag to an edge."""
    page = designer
    page.click('#editLayoutBtn')
    canvas = page.locator('#ppCanvas').bounding_box()
    _drag_to(page, PRODUCT_COL, canvas['x'] + 500, canvas['y'] + 400)
    left, top = _left_top(page, PRODUCT_COL)
    assert SAFE_MARGIN < left < CANVAS_W - SAFE_MARGIN
    assert 0 < top < CANVAS_H


def test_vertical_column_drag_moves_the_whole_band(designer):
    """Columns share ONE top: a vertical drag moves the band, so rows stay aligned.

    Only the dragged column's x moves. If the top were written to the dragged column
    alone, that column's rows would print offset from every other column's.
    """
    page = designer
    page.click('#editLayoutBtn')
    assert _left_top(page, PRODUCT_COL)[1] == 300
    assert _left_top(page, AMOUNT_COL) == [700, 300]

    canvas = page.locator('#ppCanvas').bounding_box()
    box = page.locator(PRODUCT_COL).bounding_box()
    # straight DOWN: same x, so only the band top should change
    _drag_to(page, PRODUCT_COL, box['x'] + box['width'] / 2, canvas['y'] + 560)

    p_left, p_top = _left_top(page, PRODUCT_COL)
    a_left, a_top = _left_top(page, AMOUNT_COL)
    assert p_top != 300, 'the band did not move at all'
    assert a_top == p_top, 'the undragged column kept the old top -- band split'
    assert a_left == 700, 'a vertical drag must not move another column sideways'
    assert abs(p_left - 120) <= 1, 'a vertical drag must not move the dragged column sideways'


def _col_width(page, selector):
    return page.locator(selector).evaluate("e => parseInt(e.style.width)")


def test_column_resize_clamps_at_min_width_but_not_before(designer):
    """The right-edge handle resizes freely down to COL_WIDTH_MIN, then holds."""
    page = designer
    page.click('#editLayoutBtn')
    assert _col_width(page, AMOUNT_COL) == 120

    box = page.locator(AMOUNT_COL).bounding_box()
    mid_y = box['y'] + box['height'] / 2
    right = int(box['x'] + box['width'])
    # control: an in-bounds resize lands where it was dragged (not pinned to a bound)
    _drag_from(page, right - 2, mid_y, right - 42, mid_y)
    assert _col_width(page, AMOUNT_COL) == 80

    box = page.locator(AMOUNT_COL).bounding_box()
    right = int(box['x'] + box['width'])
    _drag_from(page, right - 2, mid_y, right - 200, mid_y)
    assert _col_width(page, AMOUNT_COL) == COL_WIDTH_MIN     # floor holds


# --- control strips ---------------------------------------------------------------

def _strip_label(page, selector):
    return page.locator(selector).evaluate("e => e.parentElement.textContent.trim()")


def test_control_strips_read_their_labels_from_the_dom_not_the_key(designer):
    """The designer takes NO fieldLabels/columnLabels config -- it reads data-label.

    That is only a safe simplification if the strips actually render data-label; a
    designer that fell back to the raw key would show a user "vendor_name"/"po_no".
    """
    page = designer
    page.click('#editLayoutBtn')
    fields = {k: _strip_label(page, '[data-fieldtoggle="%s"]' % k)
              for k in ('vendor_name', 'po_no', 'order_date', 'preparer')}
    assert fields == {'vendor_name': 'Vendor', 'po_no': 'PO No.',
                      'order_date': 'Order Date', 'preparer': 'Preparer'}

    cols = {k: _strip_label(page, '[data-coltoggle="%s"]' % k)
            for k in ('product', 'amount')}
    assert cols == {'product': 'Product', 'amount': 'Amount'}


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

    # Move every page-level select OFF its harness default before saving. Asserting
    # the defaults would pass against a collect() that hardcoded them -- and a paper
    # or date format that never reaches the payload is restored to the default on the
    # next page load, silently discarding the user's choice.
    page.select_option('#ppPaper', 'letter')
    page.select_option('#ppDateFormat', 'us')
    page.select_option('#ppFontFamily', 'Georgia, serif')

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
    assert payload['paper'] == 'letter'
    assert payload['dateFormat'] == 'us'
    # The EXACT ALLOWED_FONTS string from the <select> -- not the computed stack, and
    # not a prefix of it. sanitize_layout matches fontFamily by exact string against
    # ALLOWED_FONTS and silently restores the default font for anything else, so a
    # browser-normalised variant of the same face still loses the user's choice.
    assert payload['page']['fontFamily'] == 'Georgia, serif'

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


def test_font_comes_from_the_select_not_the_computed_body_stack(designer):
    """fontFamily must be the <select>'s value -- the SOURCE, not just the string.

    Picking a font and asserting the payload carries it does not pin this: the live
    preview writes the same value onto the body, so the computed stack then agrees
    with the select and either read passes. The reads diverge when the user does NOT
    touch the select. A layout stored with a font that is no longer whitelisted is
    rendered by the page's own CSS (the real template emits
    `body { font-family: {{ layout.page.fontFamily }} }`) while the select, built from
    ALLOWED_FONTS, cannot offer it and shows a whitelisted option instead. Serializing
    the computed stack in that state re-sends the non-whitelisted string, sanitize_layout
    rejects it by exact-string match, and the font silently reverts on the next load.
    A later equal-specificity rule reproduces that divergence here.
    """
    page = designer
    captured = _intercept_save(page)
    page.add_style_tag(content='body { font-family: "Papyrus", fantasy; }')

    body_font = page.evaluate("() => getComputedStyle(document.body).fontFamily")
    sel_font = page.evaluate("() => document.getElementById('ppFontFamily').value")
    assert sel_font == '"Courier New", Courier, monospace'
    assert body_font != sel_font, 'the two reads must actually diverge here'

    page.click('#editLayoutBtn')          # the font select is deliberately untouched
    page.click('#saveLayoutBtn')
    page.wait_for_selector('#layoutSavedFlag', state='attached', timeout=5000)

    payload = json.loads(captured['body'])
    assert payload['page']['fontFamily'] == sel_font
    assert payload['page']['fontFamily'] != body_font


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


def test_missing_save_url_refuses_and_says_so(page, harness_url):
    """Fail closed: no saveUrl -> no designer at all, rather than an unsaveable one.

    Refusing silently is not enough: the template has ALREADY rendered "Edit Layout",
    so a bare `return false` leaves a live-looking button that does nothing and
    explains nothing (the only signal being a console.error the user never sees).
    """
    page.goto(harness_url)
    started = page.evaluate("() => initPreprintedDesigner({})")
    assert started is False
    assert page.locator('#saveLayoutBtn').count() == 0

    # user-visible outcome: a notice, and the dead Edit button taken out of reach
    page.wait_for_selector('#ppNotice', state='visible', timeout=5000)
    assert 'unavailable' in page.locator('#ppNotice').inner_text().lower()
    assert page.locator('#editLayoutBtn').is_disabled() is True

    page.locator('#editLayoutBtn').dispatch_event('click')    # still inert if forced
    assert page.locator('#ppCanvas').evaluate(
        "e => e.classList.contains('pp-editing')") is False


def test_no_edit_button_means_no_designer(page, harness_url):
    """Edit permission is the TEMPLATE's decision -- there is no canEdit config key.

    That is only a safe simplification if the designer really refuses when the
    template withheld #editLayoutBtn; otherwise a read-only viewer's page would grow
    a Save button (or the init would throw) with no permission check anywhere.
    """
    page.goto(harness_url)
    started = page.evaluate("""url => {
        document.getElementById('editLayoutBtn').remove();
        try { return initPreprintedDesigner({ saveUrl: url }); }
        catch (e) { return 'threw: ' + e.message; }
    }""", SAVE_PATH)
    assert started is False
    assert page.locator('#saveLayoutBtn').count() == 0
    assert page.locator('#addTextBtn').count() == 0
    assert page.locator('#ppElemBar').count() == 0


def test_second_init_is_refused_and_adds_no_duplicate_controls(designer):
    """initPreprintedDesigner is a GLOBAL, so a template can call it twice.

    (The eight per-document designers were IIFEs that could only run once.) A second
    run must not inject a second #saveLayoutBtn / #addTextBtn / #ppElemBar -- every
    e2e selector and the toolbar wiring assume those ids are unique.
    """
    page = designer                       # the fixture already initialised once
    again = page.evaluate("url => initPreprintedDesigner({ saveUrl: url })", SAVE_PATH)
    assert again is False
    for sel in ('#saveLayoutBtn', '#addTextBtn', '#ppElemBar'):
        assert page.locator(sel).count() == 1, 'duplicate id injected: ' + sel

    page.click('#editLayoutBtn')          # the first init's wiring still works
    assert page.locator('#saveLayoutBtn').is_visible() is True


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
