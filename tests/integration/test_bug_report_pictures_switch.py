"""SHOT-1 (owner, 22 Nov 2026: "B", then "B" to the design, then "A" to pasting): one compressed page picture per bug
report, plus one screenshot of the user's own (picked or pasted), behind a per-server switch that is OFF by default.
With the switch off the sheet is the text-only one of 23 Oct. Work order:
app-docs/bug-reports/2026-11-22-bug-report-page-picture-back.md.

CAS has no JS test harness, so the sheet is checked here by its source and in the browser pass."""
from pathlib import Path

import pytest

from app.audit.models import AuditLog
from app.bug_reports import service
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


def _login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _settings_form(**overrides):
    data = {'company_name': 'ABC Company', 'vat_registration_type': 'VAT', 'fiscal_year_start': '01',
            'apv_print_access': 'posted_only', 'sv_print_access': 'posted_only', 'cd_print_access': 'posted_only',
            'cd_check_print_access': 'posted_only', 'cr_print_access': 'posted_only'}
    data.update(overrides)
    return data


def _script(app):
    return (Path(app.root_path) / 'static' / 'js' / 'bug-report.js').read_text(encoding='utf-8')


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


# --- the switch ------------------------------------------------------------------------------------------------------

def test_the_switch_is_off_until_someone_turns_it_on(db_session):
    assert AppSettings.get_setting('bug_report_pictures') is None
    assert service.pictures_enabled() is False


def test_signed_out_pages_are_never_told_of_pictures(client, db_session):
    AppSettings.set_setting('bug_report_pictures', '1')
    html = client.get('/login').get_data(as_text=True)
    assert 'data-pictures' not in html and 'modern-screenshot' not in html


def test_company_settings_turns_the_switch_on_and_it_is_audited(client, db_session, admin_user, main_branch):
    _login(client)
    resp = client.post('/settings', data=_settings_form(bug_report_pictures='y'), follow_redirects=True)
    assert resp.status_code == 200
    assert AppSettings.get_setting('bug_report_pictures') == '1'
    assert service.pictures_enabled() is True
    audit = AuditLog.query.filter_by(module='settings', action='update').order_by(AuditLog.id.desc()).first()
    assert audit is not None and 'bug_report_pictures' in (audit.new_values or '')


def test_company_settings_turns_the_switch_off_again(client, db_session, admin_user, main_branch):
    AppSettings.set_setting('bug_report_pictures', '1')
    _login(client)
    resp = client.post('/settings', data=_settings_form(), follow_redirects=True)      # the tick left out = unticked
    assert resp.status_code == 200
    assert AppSettings.get_setting('bug_report_pictures') == '0'
    assert service.pictures_enabled() is False


def test_the_settings_page_shows_the_tick_with_its_label(client, db_session, admin_user, main_branch):
    _login(client)
    html = client.get('/settings').get_data(as_text=True)
    assert 'name="bug_report_pictures"' in html
    assert 'Bug reports include a page picture' in html
    assert '30 days after the report is closed' in html


def test_pictures_are_kept_30_days_after_closing(app):
    assert service.LIMITS['keep_pictures_days'] == 30
    assert '30 days' in service.purge_old_pictures.__doc__


# --- the print pages carry the same script tag as every other page ----------------------------------------------------

def test_the_print_pages_script_tag_matches_the_main_one(app):
    templates = Path(app.root_path) / 'templates'
    base = (templates / 'base.html').read_text(encoding='utf-8')
    printed = (templates / '_print_report_button.html').read_text(encoding='utf-8')
    tag = _between(base, "<script src=\"{{ url_for('static', filename='js/bug-report.js') }}", '</script>')
    assert "?v=3" in tag
    assert "{% if bug_report_pictures %}" in tag and 'data-pictures="1"' in tag and 'data-lib=' in tag
    assert tag in printed


# --- the sheet (source) ------------------------------------------------------------------------------------------------

def test_the_script_takes_no_picture_unless_the_page_says_the_switch_is_on(app):
    src = _script(app)
    assert 'var PICTURES = !!script && script.getAttribute("data-pictures") === "1";' in src
    opener = _between(src, 'function open()', 'function show(')
    # the text-only sheet comes first: nothing of the picture library is touched on that path
    assert opener.index('if (!PICTURES)') < opener.index('if (tooLong())') < opener.index('capturePage')
    assert 'loadLib' not in _between(opener, 'if (!PICTURES)', 'if (tooLong())')


def test_with_the_switch_off_the_sheet_sends_text_only_and_offers_no_screenshot(app):
    src = _script(app)
    sheet = _between(src, 'function show(', '/* The topbar button')
    assert 'var payload = PICTURES ? { message: text, context: ctx, images: images } : { message: text, context: ctx };' in sheet
    assert 'PICTURES ? pictureBlock : null' in sheet
    assert 'PICTURES ? ownBlock : null' in sheet
    assert 'if (PICTURES) form.addEventListener("paste"' in sheet
    # both wordings of "too large": the text-only one is the one of 23 Oct
    assert 'The report is too large to send. Shorten what you wrote and try again.' in src
    assert 'The report is too large. Untick the picture and send again.' in src


def test_pictures_are_jpeg_of_about_150_kb_at_most_1600_px(app):
    src = _script(app)
    assert 'var MAX_SIDE = 1600;' in src
    assert 'var MAX_PICTURE = 150 * 1024;' in src
    jpeg = _between(src, 'function toJpeg(', 'function capturePage(')
    assert 'toDataURL("image/jpeg"' in jpeg and 'image/png' not in jpeg and 'image/webp' not in jpeg


def test_the_users_own_screenshot_can_be_picked_or_pasted_and_there_is_only_one(app):
    src = _script(app)
    sheet = _between(src, 'function show(', '/* The topbar button')
    assert 'function setOwn(' in sheet
    # the file picker and Ctrl+V both go through setOwn, which replaces what was there
    assert sheet.count('setOwn(') >= 3
    paste = _between(sheet, 'form.addEventListener("paste"', '});')
    assert 'clipboardData' in paste and 'getAsFile()' in paste
    assert 'indexOf("image/") === 0' in paste
    assert 'e.preventDefault()' in paste           # only when a picture was pasted: pasting text still types it
    # Cells copied from Excel carry their text AND a bitmap of themselves: that is a text paste, not a screenshot.
    assert 'items[i].type === "text/plain"' in paste
    assert paste.index('"text/plain"') < paste.index('getAsFile()')
    assert 'Add your own screenshot' in sheet and 'paste one with Ctrl+V' in sheet


def test_the_sheet_says_when_the_server_left_a_picture_out(app):
    src = _script(app)
    assert 'left_out' in src
    # the server's reason may be the picture's size or kind, or no room on its disk: the sheet does not guess
    assert 'Sent, but without the picture: the server could not keep it.' in src
    assert 'Sent, but without one of the pictures: the server could not keep it.' in src
