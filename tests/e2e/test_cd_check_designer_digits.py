"""Playwright e2e for per-digit placement of the boxed check date.

Drives the real app/static/js/cd_check_designer.js against a static stand-in page
(tests/e2e/_cd_check_designer_harness.html) served over HTTP, the same way
test_preprinted_designer_shared.py drives the shared designer. HTTP rather than file://
so the save POST is same-origin and can be intercepted with `page.route`.

The gestures under test, one job each and no modifier key to learn: dragging a DIGIT
moves that digit alone and horizontally only, and dragging the run's GRIP -- edit-mode
chrome above the digits -- moves the whole field in both axes with every digit keeping
its offset. Digits never carry their own y, so the run cannot leave its baseline.
"""
import functools
import http.server
import json
import os
import socket
import threading

import pytest

pytestmark = [pytest.mark.e2e]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

SAVE_PATH = '/cd-check-test-save'    # the harness's data-save-url; nothing in app/ uses it
PITCH = 24                           # the harness's data-pitch
FIELD_W = 200                        # the harness date field's width
CANVAS_W = 912                       # app/cash_disbursements/check_layout.py
DATE_X, DATE_Y = 640, 90             # its starting left/top


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
def designer(page, static_server):
    """The harness with edit mode ON -- every test here is about editing."""
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(static_server + '/tests/e2e/_cd_check_designer_harness.html')
    page.click('#editLayoutBtn')
    assert page.locator('#ppCanvas.pp-editing').count() == 1, 'edit mode did not engage'
    return page


def _digit(page, i):
    return page.locator('[data-el="check_date"] .pp-digit').nth(i)


def _lefts(page):
    return page.locator('[data-el="check_date"]').evaluate(
        "e => [...e.querySelectorAll('.pp-digit')].map(d => parseInt(d.style.left))")


def _tops(page):
    return page.locator('[data-el="check_date"]').evaluate(
        "e => [...e.querySelectorAll('.pp-digit')].map(d => d.style.top || '')")


def _field_left_top(page):
    return page.locator('[data-el="check_date"]').evaluate(
        "e => [parseInt(e.style.left), parseInt(e.style.top)]")


def _drag(page, locator, dx, dy, steps=6):
    """Press the middle of `locator` and drag by (dx, dy)."""
    box = locator.bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] / 2 + dx,
                    box['y'] + box['height'] / 2 + dy, steps=steps)
    page.mouse.up()


def _intercept_save(page):
    captured = {}

    def handler(route, request):
        captured['body'] = request.post_data
        route.fulfill(status=200, content_type='application/json', body='{"ok": true}')

    page.route('**' + SAVE_PATH, handler)
    return captured


# --- horizontal drag moves ONE digit --------------------------------------------

def test_horizontal_drag_moves_only_the_grabbed_digit(designer):
    before = _lefts(designer)
    _drag(designer, _digit(designer, 2), 40, 0)
    after = _lefts(designer)
    assert after[2] == before[2] + 40
    assert after[:2] == before[:2] and after[3:] == before[3:], 'neighbours moved too'


def test_horizontal_drag_does_not_move_the_field(designer):
    _drag(designer, _digit(designer, 2), 40, 0)
    assert _field_left_top(designer) == [DATE_X, DATE_Y]


def test_a_dragged_digit_never_gets_its_own_top(designer):
    """Digits are horizontal-only: they ride the field's top, so none may take a y of
    its own. A digit with a `top` would sit off the pre-printed baseline on paper."""
    _drag(designer, _digit(designer, 3), 30, 25)
    assert _lefts(designer)[3] == 72 + 30, 'the digit did not move horizontally at all'
    assert _tops(designer) == [''] * 8


def test_digit_clamps_at_the_left_edge_of_its_field(designer):
    _drag(designer, _digit(designer, 1), -500, 0)
    assert _lefts(designer)[1] == 0


def test_digit_may_be_dragged_past_its_field_width(designer):
    """The clamp is the CANVAS, not the field box. Clamping to the field width would
    trap digits: the default check_date width is 160 while eight cells at pitch 24 need
    192, so the last two could never be separated -- they would pile up on the limit."""
    _drag(designer, _digit(designer, 7), 60, 0)
    assert _lefts(designer)[7] == 168 + 60 > FIELD_W


def test_digit_clamps_so_its_cell_stays_on_the_canvas(designer):
    _drag(designer, _digit(designer, 6), 250, 0)
    assert _lefts(designer)[6] == CANVAS_W - DATE_X - PITCH


# --- pitch re-spreads -------------------------------------------------------------

def test_editing_pitch_respreads_every_digit_evenly(designer):
    """The pitch input doubles as the reset: after hand-nudging digits, typing a pitch
    lays them out evenly again, so there is no way to get stuck with a mangled run."""
    _drag(designer, _digit(designer, 2), 40, 0)
    _drag(designer, _digit(designer, 5), -20, 0)
    pitch_input = designer.locator('#ppFieldControls input[type="number"]')
    pitch_input.fill('30')
    pitch_input.dispatch_event('input')
    assert _lefts(designer) == [0, 30, 60, 90, 120, 150, 180, 210]


# --- what gets saved ---------------------------------------------------------------

def test_save_posts_the_offsets_the_digits_actually_sit_at(designer):
    captured = _intercept_save(designer)
    _drag(designer, _digit(designer, 2), 46, 0)
    designer.click('#saveLayoutBtn')
    designer.wait_for_function("() => document.getElementById('layoutSavedFlag') !== null")
    sent = json.loads(captured['body'])['fields']['check_date']
    assert sent['digitOffsets'] == [0, 24, 94, 72, 96, 120, 144, 168]
    assert sent['boxed'] is True and sent['pitch'] == PITCH


def test_save_omits_offsets_for_a_field_that_is_not_boxed(designer):
    """Only a boxed date has digit cells; every other field posts an empty list rather
    than inventing offsets the sanitizer would have to strip."""
    captured = _intercept_save(designer)
    designer.click('#saveLayoutBtn')
    designer.wait_for_function("() => document.getElementById('layoutSavedFlag') !== null")
    fields = json.loads(captured['body'])['fields']
    assert fields['payee']['digitOffsets'] == []
    assert fields['amount_in_words']['digitOffsets'] == []


# --- edit mode gates it ------------------------------------------------------------

def test_digits_do_not_move_outside_edit_mode(page, static_server):
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(static_server + '/tests/e2e/_cd_check_designer_harness.html')
    before = _lefts(page)
    _drag(page, _digit(page, 2), 40, 0)
    assert _lefts(page) == before


# --- the whole run moves by its grip ---------------------------------------------

def _grip(page):
    return page.locator('[data-el="check_date"] .pp-boxed-grip')


def test_the_boxed_container_is_a_real_hit_box(designer):
    """REGRESSION. Absolutely positioning the digits collapsed the container to 200x0:
    it kept its width but lost all height, so the date field had no grabbable area at
    all and could only be moved by the vertical-drag-on-a-digit gesture. Shipped to
    production 2026-09-18. An explicit width alone is not a hit box -- assert the box."""
    box = designer.locator('[data-el="check_date"]').bounding_box()
    assert box['width'] == FIELD_W
    assert box['height'] > 0, 'container collapsed to zero height -- nothing to grab'


def test_the_grip_exists_only_in_edit_mode(page, static_server):
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(static_server + '/tests/e2e/_cd_check_designer_harness.html')
    assert not _grip(page).is_visible(), 'the grip is edit chrome; it must not show otherwise'
    page.click('#editLayoutBtn')
    assert _grip(page).is_visible()
    page.click('#editLayoutBtn')                      # Exit Edit
    assert not _grip(page).is_visible()


def test_dragging_the_grip_moves_the_whole_run_horizontally(designer):
    lefts_before = _lefts(designer)
    _drag(designer, _grip(designer), 70, 0)
    x, y = _field_left_top(designer)
    assert x == DATE_X + 70 and y == DATE_Y
    assert _lefts(designer) == lefts_before, 'digits keep their offsets when the run moves'


def test_dragging_the_grip_moves_the_run_in_both_axes(designer):
    """The grip is the ONE gesture that moves the field, so it must carry y as well --
    otherwise nothing can move the run vertically once the digit coupling is gone."""
    _drag(designer, _grip(designer), 40, 50)
    assert _field_left_top(designer) == [DATE_X + 40, DATE_Y + 50]


def test_a_hand_nudged_run_keeps_its_shape_when_moved(designer):
    """Registration workflow: nudge the groups to match the pre-printed boxes, then
    slide the whole run onto them. The second step must not undo the first."""
    _drag(designer, _digit(designer, 2), 22, 0)       # open a gap before DD
    _drag(designer, _digit(designer, 3), 22, 0)
    shaped = _lefts(designer)
    assert shaped[2] == 70 and shaped[3] == 94
    _drag(designer, _grip(designer), -60, 0)
    assert _lefts(designer) == shaped
    assert _field_left_top(designer)[0] == DATE_X - 60


def test_the_grip_is_not_serialized_as_a_digit(designer):
    captured = _intercept_save(designer)
    _drag(designer, _grip(designer), 30, 0)
    designer.click('#saveLayoutBtn')
    designer.wait_for_function("() => document.getElementById('layoutSavedFlag') !== null")
    sent = json.loads(captured['body'])['fields']['check_date']
    assert sent['digitOffsets'] == [0, 24, 48, 72, 96, 120, 144, 168]   # 8, not 9
    assert sent['x'] == DATE_X + 30


# --- the digit gesture is now purely horizontal ------------------------------------

def test_a_vertical_drag_on_a_digit_no_longer_moves_the_run(designer):
    """Superseded by the grip. With one gesture per job, a diagonal drag on a digit can
    no longer silently move two things at once."""
    _drag(designer, _digit(designer, 4), 0, 60)
    assert _field_left_top(designer) == [DATE_X, DATE_Y]


def test_a_diagonal_drag_on_a_digit_moves_only_that_digit_sideways(designer):
    _drag(designer, _digit(designer, 4), 40, 60)
    assert _field_left_top(designer) == [DATE_X, DATE_Y]
    assert _lefts(designer) == [0, 24, 48, 72, 136, 120, 144, 168]
    assert _tops(designer) == [''] * 8

def test_the_grip_stays_reachable_when_the_run_is_at_the_canvas_top(designer):
    """The grip sits ABOVE the digits, so slamming the run to y=0 would push the grip off
    the canvas and strand the field with nothing to grab -- the same trap the zero-height
    container created, reachable with one drag. It must flip below the run instead."""
    _drag(designer, _grip(designer), 0, -DATE_Y - 40)          # slam it to the top
    assert _field_left_top(designer)[1] == 0
    grip_box = _grip(designer).bounding_box()
    canvas_box = designer.locator('#ppCanvas').bounding_box()
    assert grip_box['y'] >= canvas_box['y'], 'the grip escaped above the canvas'
    _drag(designer, _grip(designer), 35, 0)                    # and still drags the run
    assert _field_left_top(designer)[0] == DATE_X + 35
