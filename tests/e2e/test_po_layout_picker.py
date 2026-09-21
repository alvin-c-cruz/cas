"""Playwright e2e for the PO print screen's named-layout picker
(the layoutPicker wiring in app/static/js/preprinted_designer.js).

Same static-harness shape as test_cd_check_designer_digits.py and
test_preprinted_designer_shared.py: a stand-in page (_po_layout_picker_harness.html)
served over plain HTTP (not file://, so same-origin POSTs can be intercepted with
page.route) driving the real JS file. The harness carries two named layouts with
deliberately different field geometry so a test can tell whether picking one
actually repainted the canvas, not just changed a <select> value nobody reads.

Decision 3 of the named-print-layouts plan is the test this file exists for:
picking a layout in #ppLayoutPicker only changes what is being EDITED. It must
NEVER repoint this workstation -- only #ppUseHereBtn does that. Silently
repointing the desk when an accountant opens another printer's layout to fix it is
the original bug this feature exists to kill.
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

# Made-up paths; nothing in app/ uses them -- a designer that ignored config and
# POSTed a hardcoded purchase-orders URL would miss the route and fail these tests.
SAVE_AS_PATH = '/pp-test-save-as'
RENAME_PATH = '/pp-test-rename'
DELETE_PATH = '/pp-test-delete'
SELECT_PATH = '/pp-test-select'


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
    return static_server + '/tests/e2e/_po_layout_picker_harness.html'


@pytest.fixture
def designer(page, harness_url):
    """Harness page with the shared designer initialised and layoutPicker wired.

    Not edit-mode-gated: in the real template the picker toolbar sits beside, not
    inside, the drag-editor chrome (font/paper/date selects), so no #editLayoutBtn
    click is needed for it to be usable -- matching how the print screen renders it
    for every can_edit_layout user regardless of whether they ever enter Edit Layout.
    """
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(harness_url)
    started = page.evaluate(
        """(urls) => initPreprintedDesigner({
            saveUrl: '/pp-test-save',
            layoutPicker: {
                saveAsUrl: urls.saveAs, renameUrl: urls.rename,
                deleteUrl: urls.delete, selectUrl: urls.select, branchId: 1,
            },
        })""",
        {'saveAs': SAVE_AS_PATH, 'rename': RENAME_PATH, 'delete': DELETE_PATH, 'select': SELECT_PATH})
    assert started is True, 'initPreprintedDesigner did not initialise'
    return page


def _intercept(page, path, body='{"ok": true}', status=200):
    """Route a configured endpoint and record what the designer POSTed to it."""
    captured = {}

    def handler(route, request):
        captured['body'] = request.post_data
        route.fulfill(status=status, content_type='application/json', body=body)

    page.route('**' + path, handler)
    return captured


def _po_no_left(page):
    return page.locator('[data-el="po_no"]').evaluate("e => parseInt(e.style.left)")


# --- Decision 3: picking never repoints the workstation ---------------------------

def test_picking_in_the_designer_does_not_repoint_the_workstation(designer):
    """An accountant at the Malandag desk fixing the LaserJet layout must not
    silently repoint Malandag at it -- that is the original bug, with a name on it."""
    before = designer.locator('#ppDeviceLayout').inner_text()
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    assert designer.locator('#ppDeviceLayout').inner_text() == before


def test_use_on_this_workstation_is_what_repoints_it(designer):
    _intercept(designer, SELECT_PATH)
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    designer.click('#ppUseHereBtn')
    designer.wait_for_function(
        "() => document.getElementById('ppDeviceLayout').textContent.includes('HP LaserJet')")


# --- picking really does change what is being edited -------------------------------

def test_picking_a_layout_repaints_the_canvas_fields(designer):
    """Decision 3's other half: the picker changes real geometry, not a dropdown
    value nobody acts on."""
    assert _po_no_left(designer) == 620              # the harness's starting position
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    assert _po_no_left(designer) == 640


def test_picking_the_default_back_restores_its_own_geometry(designer):
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    designer.select_option('#ppLayoutPicker', label='Default')
    assert _po_no_left(designer) == 620


# --- Save as... ---------------------------------------------------------------

def test_save_as_posts_the_name_and_the_current_canvas_over_the_configured_url(designer):
    captured = _intercept(designer, SAVE_AS_PATH,
                          body='{"ok": true, "layout_id": 9, "name": "Purchasing - Epson"}')
    designer.evaluate("() => { window.prompt = () => 'Purchasing - Epson'; }")
    designer.click('#ppSaveAsBtn')
    designer.wait_for_function(
        """name => [...document.getElementById('ppLayoutPicker').options]
            .some(o => o.textContent === name)""",
        arg='Purchasing - Epson')
    body = json.loads(captured['body'])
    assert body['name'] == 'Purchasing - Epson'
    assert body['branch_id'] == 1
    # the layout content, not just the name -- see build_layout_api's sanitize_layout
    assert set(body) >= {'paper', 'dateFormat', 'page', 'fields', 'lineItems', 'extras', 'texts'}
    assert designer.locator('#ppLayoutPicker').input_value() == '9'   # newly saved one selected


def test_save_as_declined_posts_nothing(designer):
    captured = _intercept(designer, SAVE_AS_PATH)
    designer.evaluate("() => { window.prompt = () => null; }")
    designer.click('#ppSaveAsBtn')
    designer.wait_for_timeout(200)
    assert 'body' not in captured


# --- Rename -------------------------------------------------------------------

def test_rename_updates_the_picker_option_text(designer):
    _intercept(designer, RENAME_PATH)
    designer.evaluate("() => { window.prompt = () => 'Purchasing - Front Counter'; }")
    designer.click('#ppRenameBtn')
    designer.wait_for_function(
        "() => document.getElementById('ppLayoutPicker').selectedOptions[0].textContent "
        "=== 'Purchasing - Front Counter'")


# --- Delete -------------------------------------------------------------------

def test_delete_removes_the_option(designer):
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    _intercept(designer, DELETE_PATH)
    designer.evaluate("() => { window.confirm = () => true; }")
    designer.click('#ppDeleteLayoutBtn')
    designer.wait_for_function(
        """() => ![...document.getElementById('ppLayoutPicker').options]
            .some(o => o.textContent === 'Purchasing - HP LaserJet')""")


def test_delete_declined_posts_nothing_and_keeps_the_option(designer):
    designer.select_option('#ppLayoutPicker', label='Purchasing - HP LaserJet')
    captured = _intercept(designer, DELETE_PATH)
    designer.evaluate("() => { window.confirm = () => false; }")
    designer.click('#ppDeleteLayoutBtn')
    designer.wait_for_timeout(200)
    assert 'body' not in captured
    assert designer.locator('#ppLayoutPicker option', has_text='Purchasing - HP LaserJet').count() == 1


# --- a refused write surfaces the server's message, never fails silently ----------

def test_a_refused_use_here_shows_the_servers_message(designer):
    designer.route('**' + SELECT_PATH, lambda route, request: route.fulfill(
        status=404, content_type='application/json',
        body='{"ok": false, "error": "That layout no longer exists. Refresh and try again."}'))
    designer.click('#ppUseHereBtn')
    designer.wait_for_selector('#ppNotice', state='visible', timeout=5000)
    assert 'no longer exists' in designer.locator('#ppNotice').inner_text()
    # and Decision 3 holds even on a refusal: nothing repointed
    assert designer.locator('#ppDeviceLayout').inner_text() == 'Default'
