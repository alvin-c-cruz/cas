"""Bug report tables and statuses (spec 2026-10-15-bug-reports-design.md, section 3)."""
import json

import pytest

from app import db
from app.bug_reports.models import BugReport, BugReportImage
from app.bug_reports.statuses import (
    CLOSED_STATUSES, OPEN_STATUSES, STATUS_LABEL, STATUSES, is_closed, is_status,
)

pytestmark = [pytest.mark.integration, pytest.mark.bug_reports]


def test_statuses_are_sanays_set():
    assert OPEN_STATUSES == ('new', 'seen', 'in_progress')
    assert CLOSED_STATUSES == ('fixed', 'wont_fix', 'duplicate', 'cant_reproduce')
    assert STATUSES == OPEN_STATUSES + CLOSED_STATUSES
    assert STATUS_LABEL == {
        'new': 'New', 'seen': 'Seen', 'in_progress': 'In progress', 'fixed': 'Fixed',
        'wont_fix': "Won't fix", 'duplicate': 'Duplicate', 'cant_reproduce': "Can't reproduce",
    }
    assert is_status('wont_fix') and not is_status('closed') and not is_status(None)
    assert is_closed('duplicate') and not is_closed('in_progress')


def test_report_and_picture_round_trip(db_session, admin_user):
    report = BugReport(user_id=admin_user.id, message='It broke',
                       context=json.dumps({'where': {'path': '/sales-invoices?status=draft'}}))
    db.session.add(report)
    db.session.flush()
    db.session.add(BugReportImage(report_id=report.id, kind='page', mime='image/jpeg',
                                  stored_name='abc.jpg', size_bytes=3))
    db.session.commit()

    got = db.session.get(BugReport, report.id)
    assert got.status == 'new'
    assert got.closed_at is None
    assert got.created_at is not None
    assert got.user.username == 'admin'
    assert [im.stored_name for im in got.images] == ['abc.jpg']
    assert got.images[0].report is got
    assert got.page_path == '/sales-invoices?status=draft'


def test_bad_context_reads_as_empty(db_session, admin_user):
    assert BugReport(user_id=admin_user.id, message='x', context='not json').context_data == {}
    assert BugReport(user_id=admin_user.id, message='x', context='[1, 2]').context_data == {}
    assert BugReport(user_id=admin_user.id, message='x', context='{"where": "x"}').page_path is None


def test_no_branch_id_so_branch_deletes_never_see_reports():
    assert 'branch_id' not in BugReport.__table__.c.keys()
    assert 'branch_id' not in BugReportImage.__table__.c.keys()
