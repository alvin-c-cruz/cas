"""The administrator's Bug Reports pages (spec sections 4 and 5)."""
import json
import os
from datetime import timedelta

import pytest

from app import db
from app.audit.models import AuditLog
from app.bug_reports import service
from app.bug_reports.models import BugReport, BugReportImage
from app.errors.models import ErrorLog
from app.utils import ph_now
from tests.integration._bug_report_helpers import JPEG, login

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


@pytest.fixture
def uploads(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    return tmp_path


def _report(user, status='new', created=None, closed=None, images=(), message='Broken'):
    report_id = service.create_report(user, message, {'where': {'path': '/sales-invoices/3'}},
                                      list(images), created or ph_now())
    report = db.session.get(BugReport, report_id)
    if status != 'new':
        report.status = status
        report.closed_at = closed
        db.session.commit()
    return report


def test_non_admins_are_refused_on_every_admin_route(app, db_session, admin_user, accountant_user,
                                                     chief_accountant_user, main_branch, uploads):
    report = _report(admin_user, images=[('page', 'image/jpeg', JPEG)])
    urls = ['/admin/bug-reports', f'/admin/bug-reports/{report.id}',
            f'/admin/bug-reports/{report.id}/images/{report.images[0].id}']
    for user, password in ((accountant_user, 'accountant123'), (chief_accountant_user, 'chief123')):
        client = app.test_client()
        login(client, user, password, main_branch)
        for url in urls:
            assert client.get(url).status_code == 302, url
        assert client.post(f'/admin/bug-reports/{report.id}/status', data={'status': 'fixed'}).status_code == 302
    db.session.expire_all()
    assert db.session.get(BugReport, report.id).status == 'new'


def test_list_tabs_counts_and_rows(client, admin_user, main_branch, uploads):
    _report(admin_user, message='open one')
    _report(admin_user, status='in_progress', message='working on it')
    _report(admin_user, status='fixed', closed=ph_now(), message='done one')
    login(client, admin_user, 'admin123', main_branch)

    html = client.get('/admin/bug-reports').get_data(as_text=True)
    assert 'Open · 2' in html and 'Closed · 1' in html and 'All · 3' in html
    assert 'open one' in html and 'working on it' in html and 'done one' not in html
    assert '/sales-invoices/3' in html

    html = client.get('/admin/bug-reports?show=closed').get_data(as_text=True)
    assert 'done one' in html and 'open one' not in html

    html = client.get('/admin/bug-reports?show=all').get_data(as_text=True)
    assert all(m in html for m in ('open one', 'working on it', 'done one'))


def test_empty_states(client, admin_user, main_branch, uploads):
    login(client, admin_user, 'admin123', main_branch)
    assert 'No open reports.' in client.get('/admin/bug-reports').get_data(as_text=True)
    assert 'No closed reports.' in client.get('/admin/bug-reports?show=closed').get_data(as_text=True)
    assert 'No reports yet.' in client.get('/admin/bug-reports?show=all').get_data(as_text=True)


def test_detail_shows_message_pictures_context_and_the_users_nearby_errors(client, admin_user, staff_user,
                                                                          main_branch, uploads):
    now = ph_now()
    report = _report(staff_user, created=now, images=[('page', 'image/jpeg', JPEG)], message='Line 1\nLine 2')
    db.session.add_all([
        ErrorLog(severity='ERROR', error_type='ValueError', error_message='inside the window',
                 user_id=staff_user.id, timestamp=now - timedelta(minutes=10)),
        ErrorLog(severity='ERROR', error_type='KeyError', error_message='too early',
                 user_id=staff_user.id, timestamp=now - timedelta(minutes=31)),
        ErrorLog(severity='ERROR', error_type='TypeError', error_message='someone else',
                 user_id=admin_user.id, timestamp=now - timedelta(minutes=5)),
    ])
    db.session.commit()
    login(client, admin_user, 'admin123', main_branch)

    html = client.get(f'/admin/bug-reports/{report.id}').get_data(as_text=True)
    assert 'Line 1\nLine 2' in html
    assert f'/admin/bug-reports/{report.id}/images/{report.images[0].id}' in html
    assert 'Server errors around this report' in html
    assert 'inside the window' in html and 'too early' not in html and 'someone else' not in html
    assert '/sales-invoices/3' in html
    db.session.expire_all()
    assert db.session.get(BugReport, report.id).status == 'new'  # opening does not mark it seen


def test_detail_hides_the_errors_panel_when_there_are_none(client, admin_user, main_branch, uploads):
    report = _report(admin_user)
    login(client, admin_user, 'admin123', main_branch)
    assert 'Server errors around this report' not in client.get(f'/admin/bug-reports/{report.id}').get_data(as_text=True)


def test_status_changes_follow_the_closed_at_rules_and_are_audited(client, admin_user, main_branch, uploads):
    report = _report(admin_user)
    login(client, admin_user, 'admin123', main_branch)

    def set_status(status):
        resp = client.post(f'/admin/bug-reports/{report.id}/status', data={'status': status})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(f'/admin/bug-reports/{report.id}')
        db.session.expire_all()
        return db.session.get(BugReport, report.id)

    got = set_status('seen')
    assert got.status == 'seen' and got.closed_at is None
    got = set_status('fixed')
    first_closed = got.closed_at
    assert first_closed is not None
    got = set_status('duplicate')
    assert got.status == 'duplicate' and got.closed_at == first_closed  # moving between closed keeps it
    got = set_status('in_progress')
    assert got.closed_at is None                                        # reopening clears it

    rows = (AuditLog.query.filter_by(module='bug_report', action='update', record_id=report.id)
            .order_by(AuditLog.id).all())
    assert [(json.loads(a.old_values)['status'], json.loads(a.new_values)['status']) for a in rows] == [
        ('new', 'seen'), ('seen', 'fixed'), ('fixed', 'duplicate'), ('duplicate', 'in_progress')]


def test_the_same_status_again_changes_nothing(client, admin_user, main_branch, uploads):
    report = _report(admin_user)
    login(client, admin_user, 'admin123', main_branch)
    client.post(f'/admin/bug-reports/{report.id}/status', data={'status': 'fixed'})
    db.session.expire_all()
    closed = db.session.get(BugReport, report.id).closed_at
    client.post(f'/admin/bug-reports/{report.id}/status', data={'status': 'fixed'})
    db.session.expire_all()
    assert db.session.get(BugReport, report.id).closed_at == closed
    assert AuditLog.query.filter_by(module='bug_report', action='update', record_id=report.id).count() == 1


def test_a_bad_status_is_refused(client, admin_user, main_branch, uploads):
    report = _report(admin_user)
    login(client, admin_user, 'admin123', main_branch)
    resp = client.post(f'/admin/bug-reports/{report.id}/status', data={'status': 'closed'}, follow_redirects=True)
    assert 'That is not a bug report status.' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(BugReport, report.id).status == 'new'


def test_a_picture_is_served_privately(client, admin_user, main_branch, uploads):
    report = _report(admin_user, images=[('page', 'image/jpeg', JPEG)])
    login(client, admin_user, 'admin123', main_branch)
    resp = client.get(f'/admin/bug-reports/{report.id}/images/{report.images[0].id}')
    assert resp.status_code == 200
    assert resp.data == JPEG
    assert resp.headers['Content-Type'] == 'image/jpeg'
    assert resp.headers['Cache-Control'] == 'private, no-store'
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['Content-Security-Policy'] == "default-src 'none'; sandbox"


def test_another_reports_picture_or_a_missing_file_is_404(client, admin_user, main_branch, uploads):
    a = _report(admin_user, images=[('page', 'image/jpeg', JPEG)])
    b = _report(admin_user, images=[('page', 'image/jpeg', JPEG)])
    login(client, admin_user, 'admin123', main_branch)
    assert client.get(f'/admin/bug-reports/{a.id}/images/{b.images[0].id}').status_code == 404
    os.remove(uploads / 'bug_reports' / str(a.id) / a.images[0].stored_name)
    assert client.get(f'/admin/bug-reports/{a.id}/images/{a.images[0].id}').status_code == 404


def test_opening_the_list_deletes_pictures_of_reports_closed_over_90_days_ago(client, admin_user, main_branch,
                                                                              uploads):
    now = ph_now()
    old = _report(admin_user, status='fixed', closed=now - timedelta(days=91), images=[('page', 'image/jpeg', JPEG)])
    recent = _report(admin_user, status='fixed', closed=now - timedelta(days=89), images=[('page', 'image/jpeg', JPEG)])
    still_open = _report(admin_user, images=[('page', 'image/jpeg', JPEG)])
    old_id, keep_ids = old.id, (recent.id, still_open.id)
    login(client, admin_user, 'admin123', main_branch)

    assert client.get('/admin/bug-reports?show=all').status_code == 200

    db.session.expire_all()
    assert db.session.get(BugReport, old_id) is not None             # the report itself stays
    assert BugReportImage.query.filter_by(report_id=old_id).count() == 0
    assert not (uploads / 'bug_reports' / str(old_id)).exists()
    for report_id in keep_ids:
        assert BugReportImage.query.filter_by(report_id=report_id).count() == 1
        assert (uploads / 'bug_reports' / str(report_id)).is_dir()


def test_the_purge_tolerates_a_file_already_gone(db_session, admin_user, uploads):
    now = ph_now()
    old = _report(admin_user, status='fixed', closed=now - timedelta(days=100), images=[('page', 'image/jpeg', JPEG)])
    os.remove(uploads / 'bug_reports' / str(old.id) / old.images[0].stored_name)
    assert service.purge_old_pictures(now) == 1
    assert BugReportImage.query.count() == 0


def test_counts(db_session, admin_user, uploads):
    _report(admin_user)
    _report(admin_user)
    _report(admin_user, status='seen')
    _report(admin_user, status='wont_fix', closed=ph_now())
    assert service.new_report_count() == 2
    assert service.report_counts() == {'open': 3, 'closed': 1, 'all': 4}
