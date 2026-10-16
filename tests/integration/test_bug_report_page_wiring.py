"""The button, the script and the admin's sidebar link with its New count (spec sections 1 and 5)."""
import pytest

from app.bug_reports import service
from app.utils import ph_now
from tests.integration._bug_report_helpers import login

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


@pytest.fixture
def uploads(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    return tmp_path


def _page(client):
    resp = client.get('/profile')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_signed_in_pages_carry_the_button_and_the_script(client, accountant_user, main_branch):
    login(client, accountant_user, 'accountant123', main_branch)
    html = _page(client)
    assert f'data-report-user="{accountant_user.id}"' in html
    assert 'data-report-open' in html
    assert 'aria-label="Report a problem"' in html
    assert '/static/js/bug-report.js' in html
    assert '/static/css/bug-report.css' in html
    assert 'data-endpoint="/bug-reports"' in html
    assert 'data-lib="/static/vendor/modern-screenshot-4.7.0.js"' in html


def test_signed_out_pages_do_not(client, db_session):
    html = client.get('/login').get_data(as_text=True)
    assert '/static/js/bug-report.js' not in html
    assert 'data-report-user=' not in html


def test_the_admin_sidebar_shows_the_new_count(client, admin_user, staff_user, main_branch, uploads):
    first = service.create_report(staff_user, 'one', {}, [], ph_now())
    service.create_report(staff_user, 'two', {}, [], ph_now())
    login(client, admin_user, 'admin123', main_branch)
    html = _page(client)
    assert 'href="/admin/bug-reports"' in html
    assert 'id="nav-bug-report-badge">2<' in html

    client.post(f'/admin/bug-reports/{first}/status', data={'status': 'seen'})
    assert 'id="nav-bug-report-badge">1<' in _page(client)


def test_no_badge_when_nothing_is_new(client, admin_user, main_branch, uploads):
    login(client, admin_user, 'admin123', main_branch)
    html = _page(client)
    assert 'href="/admin/bug-reports"' in html
    assert 'id="nav-bug-report-badge"' not in html


def test_non_admins_get_no_link(client, accountant_user, chief_accountant_user, main_branch, app):
    for user, password in ((accountant_user, 'accountant123'), (chief_accountant_user, 'chief123')):
        c = app.test_client()
        login(c, user, password, main_branch)
        html = _page(c)
        assert 'href="/admin/bug-reports"' not in html
        assert 'nav-bug-report-badge' not in html


def test_a_failing_badge_count_is_logged_and_the_page_still_renders(
        client, admin_user, main_branch, uploads, monkeypatch, caplog):
    def boom():
        raise RuntimeError('boom')

    monkeypatch.setattr(service, 'new_report_count', boom)
    login(client, admin_user, 'admin123', main_branch)
    with caplog.at_level('ERROR'):
        html = _page(client)
    assert 'href="/admin/bug-reports"' in html
    assert 'id="nav-bug-report-badge"' not in html
    assert 'could not count New reports for the sidebar badge' in caplog.text
