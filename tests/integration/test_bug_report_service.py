"""Storing a report (spec section 4, "Create", step 7) and the server's own context."""
import json
from datetime import timedelta

import pytest

from app import db
from app.audit.models import AuditLog
from app.bug_reports import service
from app.bug_reports.models import BugReport
from app.notifications.models import Notification
from app.users.models import User
from app.utils import ph_now

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


@pytest.fixture
def uploads(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    return tmp_path


def _files(root):
    return sorted(p.name for p in root.rglob('*') if p.is_file())


def test_create_report_stores_the_report_notifications_and_audit_and_no_file(db_session, admin_user,
                                                                             staff_user, uploads):
    second = User(username='admin2', email='a2@test.com', full_name='Second Admin', role='admin', is_active=True)
    gone = User(username='admin3', email='a3@test.com', full_name='Gone Admin', role='admin', is_active=False)
    for u in (second, gone):
        u.set_password('not-the-default-1')
        db.session.add(u)
    db.session.commit()
    now = ph_now()
    message = 'When I click Save on the purchase order the page reloads and every line is gone'

    report_id = service.create_report(staff_user, message, {'where': {'path': '/x'}}, now)

    report = db.session.get(BugReport, report_id)
    assert report.user_id == staff_user.id
    assert report.status == 'new'
    assert report.created_at == now.replace(tzinfo=None)  # SQLite hands back the same wall time, naive
    assert json.loads(report.context) == {'where': {'path': '/x'}}
    assert report.images == []
    assert _files(uploads) == [] and not (uploads / 'bug_reports').exists()

    notes = Notification.query.filter_by(related_type='bug_report', related_id=report_id).all()
    assert sorted(n.user_id for n in notes) == sorted([admin_user.id, second.id])  # not the inactive one
    assert {(n.title, n.category, n.message) for n in notes} == {
        ('Bug report', 'info', 'Staff User: ' + service.first_words(message))}

    audit = AuditLog.query.filter_by(module='bug_report', action='create', record_id=report_id).one()
    assert audit.user_id == staff_user.id
    assert json.loads(audit.new_values) == {'message': service.first_words(message)}


def test_a_failure_part_way_leaves_nothing_behind(db_session, admin_user, staff_user, uploads, monkeypatch):
    def notifying_fails(message):
        raise RuntimeError('database is locked')

    monkeypatch.setattr(service, 'first_words', notifying_fails)  # runs once the report row is flushed
    with pytest.raises(RuntimeError):
        service.create_report(staff_user, 'boom', {}, ph_now())

    assert BugReport.query.count() == 0
    assert Notification.query.filter_by(related_type='bug_report').count() == 0


def test_reports_since_counts_this_user_inside_the_window(db_session, admin_user, staff_user, uploads):
    now = ph_now()
    for when in (now - timedelta(hours=25), now - timedelta(hours=23), now):
        service.create_report(staff_user, 'm', {}, when)
    service.create_report(admin_user, 'm', {}, now)
    assert service.reports_since(staff_user.id, now - timedelta(days=1)) == 2


def test_app_version_is_a_commit_or_empty(app, monkeypatch):
    monkeypatch.setattr(service, '_VERSION', None)
    version = service.app_version()
    assert isinstance(version, str)
    assert version == '' or (len(version) == 40 and all(c in '0123456789abcdef' for c in version))


def test_app_version_is_empty_when_git_cannot_say(app, monkeypatch):
    monkeypatch.setattr(service, '_VERSION', None)

    def no_git(*args, **kwargs):
        raise OSError('git not found')

    monkeypatch.setattr(service.subprocess, 'run', no_git)
    assert service.app_version() == ''
