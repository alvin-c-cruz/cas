"""The browser side's files are served, and the port keeps its CAS-specific changes (spec section 1).
CAS has no JS test harness; behaviour is checked in the browser pass (Task 8)."""
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


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
