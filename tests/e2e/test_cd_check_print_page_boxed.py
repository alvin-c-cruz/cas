"""Playwright e2e: the boxed-date toggle on the REAL print-check page.

The harness tests (test_cd_check_designer_digits.py) drive cd_check_designer.js against a
hand-written stand-in page. This file closes the gap between that stand-in and the
template: it renders /cash-disbursements/<id>/print-check through the Flask test client,
loads that exact HTML into Chromium with the real JS and CSS served over HTTP, and ticks
"boxed" there. If the template stops writing data-plain, or the JS and template disagree
on the markup, this fails where the harness cannot.

BUG-CHECK-BOXED-DATE-NO-PREVIEW: Philgen CDV 1722 (account 046-3, no saved layout) --
ticking "boxed" changed nothing until a Save Layout and a reload.
"""
import functools
import http.server
import json
import os
import socket
import threading

import pytest

from app.cash_disbursements.check_layout import save_layout
from tests.integration.test_cd_check_print import _check_cdv, _open

pytestmark = [pytest.mark.e2e, pytest.mark.cash_disbursements]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


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


def _load(page, client, static_server, cdv):
    """Open the rendered print-check HTML in Chromium, edit mode on, saves captured."""
    html = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
    captured = {}

    def on_save(route, request):
        captured['body'] = request.post_data
        route.fulfill(status=200, content_type='application/json', body='{"ok": true}')

    page.route('**/cash-disbursements/check-layout*', on_save)
    # /static/... -> the app/static folder on the throwaway file server.
    page.route(static_server + '/', lambda route: route.fulfill(
        status=200, content_type='text/html', body=html))
    page.set_viewport_size({'width': 1280, 'height': 1200})
    page.goto(static_server + '/')
    page.click('#editLayoutBtn')
    return captured


def _lefts(page):
    return page.locator('[data-el="check_date"]').evaluate(
        "e => [...e.querySelectorAll('.pp-digit')].map(d => parseInt(d.style.left))")


def _boxed_toggle(page):
    return page.locator('#ppFieldControls input[type="checkbox"][title="Boxed digits"]')


def test_ticking_boxed_on_an_unboxed_account_shows_the_cells(page, client, db_session, admin_user,
                                                             main_branch, static_server):
    """A layout saved unboxed (the date is boxed by default since 2 Nov 2026, so this is
    what an account that was set up before then, or unticked on purpose, looks like)."""
    cdv = _check_cdv(db_session, main_branch)            # check date 2026-07-08
    save_layout({'fields': {'check_date': {'boxed': False}}}, 'admin', account_id=cdv._cash_acct_id)
    _open(client, main_branch)
    captured = _load(page, client, static_server, cdv)
    assert _lefts(page) == []
    _boxed_toggle(page).check()
    assert _lefts(page) == [0, 24, 48, 72, 96, 120, 144, 168]
    digits = page.locator('[data-el="check_date"]').evaluate(
        "e => [...e.querySelectorAll('.pp-digit')].map(d => d.textContent).join('')")
    assert digits == '07082026'
    page.click('#saveLayoutBtn')
    page.wait_for_function("() => document.getElementById('layoutSavedFlag') !== null")
    sent = json.loads(captured['body'])['fields']['check_date']
    assert sent['boxed'] is True and sent['digitOffsets'] == [0, 24, 48, 72, 96, 120, 144, 168]


def test_a_copied_boxed_layout_unticks_to_the_plain_date(page, client, db_session, admin_user,
                                                         main_branch, static_server):
    cdv = _check_cdv(db_session, main_branch)
    save_layout({'fields': {'check_date': {'boxed': True, 'pitch': 26}}}, 'admin', account_id=9001)
    _open(client, main_branch)
    _load(page, client, static_server, cdv)
    assert _lefts(page) == [0, 26, 52, 78, 104, 130, 156, 182], 'the copied boxed layout did not load'
    _boxed_toggle(page).uncheck()
    assert _lefts(page) == []
    assert page.locator('[data-el="check_date"]').evaluate("e => e.textContent") == '07-08-2026'
