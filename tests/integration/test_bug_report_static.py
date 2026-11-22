"""The browser side's files are served, and the port keeps its CAS-specific changes (spec section 1).
CAS has no JS test harness; behaviour is checked in the browser pass (Task 8)."""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


def _script(app):
    return (Path(app.root_path) / 'static' / 'js' / 'bug-report.js').read_text(encoding='utf-8')


def _between(src, start, end):
    """The source from the first `start` up to the next `end` after it."""
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_the_files_are_served(client):
    for path, marker in (('/static/js/bug-report.js', b'window.CasReport'),
                         ('/static/css/bug-report.css', b'.cas-report-sheet'),
                         ('/static/vendor/modern-screenshot-4.7.0.js', b'modern-screenshot v4.7.0')):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert marker in resp.data, path


def test_the_script_keeps_the_cas_specific_changes(app):
    src = (Path(app.root_path) / 'static' / 'js' / 'bug-report.js').read_text(encoding='utf-8')
    assert 'createObjectURL' not in src      # CSP img-src has no blob:; own screenshots are data: URLs
    assert 'readAsDataURL' in src
    assert 'redirect: "error"' in src        # a redirect from any CAS gate never reads as sent
    assert 'res.status === 201' in src       # only a 201 is "Sent"
    assert '"x-csrftoken": csrfToken()' in src
    assert 'sessionStorage' in src           # the click and page record spans full page loads
    assert 'font: false' in src              # Google Fonts are out of the library's reach under CSP
    assert src.count('"bad_csrf"') >= 2      # the sheet path queues it, and the flush path keeps it queued
    assert 'res.status === 401' in src       # a signed-out reply stays queued too
    assert '.board' not in src               # Sanay's chess-board tracking is not ported
    for forbidden in ('alert(', 'confirm(', 'prompt('):
        assert forbidden not in src


def test_the_record_is_restored_only_for_the_user_who_left_it(app):
    """F1: another user's pages and clicks never ride along after a sign-out and sign-in in the same tab."""
    src = _script(app)
    restore = _between(src, 'var me = userId();', 'function save()')
    assert 'sessionStorage.getItem(LOG_KEY)' in restore           # read after `me` is known
    assert 'saved.user === me' in restore                         # the owner check
    assert 'window.sessionStorage.removeItem(LOG_KEY)' in restore  # anyone else's record is thrown away
    assert restore.index('saved.user === me') < restore.index('removeItem(LOG_KEY)')
    save = _between(src, 'function save()', 'function stamp()')
    assert 'JSON.stringify({ user: me, taps: log.taps, pages: log.pages, errors: log.errors, '\
           'requests: log.requests, sizes: log.sizes })' in save
    # the in-memory record keeps its shape, so _log and context() are unchanged
    assert 'var log = { taps: [], pages: [], errors: [], requests: [], sizes: [] };' in src
    assert 'before: { taps: log.taps.slice(), pages: log.pages.slice(), errors: log.errors.slice(), '\
           'requests: log.requests.slice(), sizes: log.sizes.slice() }' in src
    assert '_log: log' in src


def test_a_logout_click_clears_the_record_after_the_tap_is_written(app):
    src = _script(app)
    handler = _between(src, 'document.addEventListener("click", function (e) {', '}, true);')
    assert 'keep(log.taps' in handler
    assert 'LOGOUT.test(u.pathname)' in handler
    assert 'u.origin === location.origin' in handler
    assert handler.index('keep(log.taps') < handler.index('LOGOUT.test(') < handler.index('removeItem(LOG_KEY)')
    assert 'signedOut = true' in handler
    assert 'if (signedOut) return;' in _between(src, 'function save()', 'function stamp()')   # not re-saved
    # the pattern matches the app's real logout route (the links in base.html are GET links to it)
    pattern = re.search(r'var LOGOUT = /(.+)/;', src).group(1).replace('\\/', '/')
    with app.test_request_context():
        from flask import url_for
        assert re.search(pattern, url_for('users.logout'))


def test_a_long_page_skips_the_automatic_picture(app):
    """F2: past either size the sheet opens without a picture, at once, instead of freezing the tab."""
    src = _script(app)
    limits = _between(src, 'var LIMIT = {', 'var log = {')            # named at the top with the other limits
    assert re.search(r'var MAX_PAGE_HEIGHT = 10000;', limits)
    assert re.search(r'var MAX_ELEMENTS = 1500;', limits)   # calibrated on real CAS pages, not the ruling's 5,000
    assert ('var TOO_LONG = "This page is too long for an automatic picture. '
            'You can add your own screenshot (Windows: Win+Shift+S).";') in limits
    too_long = _between(src, 'function tooLong()', 'function afterPaint()')
    assert 'document.documentElement.scrollHeight > MAX_PAGE_HEIGHT' in too_long
    assert 'document.getElementsByTagName("*").length > MAX_ELEMENTS' in too_long
    opener = _between(src, 'function open()', 'function show(')
    # measured before the overlay or the picture library exists; the sheet opens with the message instead
    assert opener.index('if (tooLong())') < opener.index('Taking a picture of the page')
    assert opener.index('if (tooLong())') < opener.index('capturePage')
    assert 'show(sheetOnly, ctx, null, "", TOO_LONG);' in opener
    assert 'text: note || "The page picture could not be taken (' in src
    # the waiting message gets one frame to paint before the capture starts
    assert 'afterPaint().then(capturePage)' in opener
    paint = _between(src, 'function afterPaint()', 'function toJpeg(')
    assert 'requestAnimationFrame(go)' in paint and 'setTimeout(ok, 0)' in paint


def test_expired_queue_items_are_dropped_whoever_queued_them(app):
    """F3: the 7-day / 5-try drop runs before the "is it mine" skip, so a shared PC does not keep
    another user's queued report for ever."""
    src = _script(app)
    flush = _between(src, 'function runFlush()', 'chain = chain.then(')
    assert '!it.value || it.value.user !== me' not in flush
    expiry = flush.index('tries >= MAX_TRIES || (isFinite(age) && age > MAX_AGE_MS)')
    drop = flush.index('drop(r.db, it.key)', expiry)
    mine = flush.index('if (it.value.user !== me) return;')
    assert expiry < drop < mine
