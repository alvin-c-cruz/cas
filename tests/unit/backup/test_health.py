"""Task 7 — backup health (tz-safe staleness, empty=RED) + loud alert."""
from datetime import timedelta

from app import db
from app.utils import ph_now
from app.backup.models import BackupRun
from app.backup.health import backup_health


def test_no_rows_is_red(db_session):
    h = backup_health()
    assert h['state'] == 'red'
    assert 'no ' in h['reason'].lower()


def test_fresh_success_is_green(db_session):
    db.session.add(BackupRun(triggered_by='cli', status='success',
                             verified_at=ph_now(), created_at=ph_now()))
    db.session.commit()
    assert backup_health()['state'] == 'green'


def test_stale_success_is_red(db_session):
    old = (ph_now() - timedelta(hours=40)).replace(tzinfo=None)
    db.session.add(BackupRun(triggered_by='cli', status='success',
                             verified_at=old, created_at=old))
    db.session.commit()
    assert backup_health(stale_hours=30)['state'] == 'red'


def test_latest_failed_is_red(db_session):
    db.session.add(BackupRun(triggered_by='cli', status='success',
                             verified_at=ph_now(), created_at=ph_now()))
    db.session.add(BackupRun(triggered_by='cli', status='failed', created_at=ph_now()))
    db.session.commit()
    assert backup_health()['state'] == 'red'


def test_notify_if_stale_creates_notification(db_session, admin_user):
    from app.backup.alerts import notify_if_stale
    from app.notifications.models import Notification
    n = notify_if_stale()  # no backup rows -> red
    assert n >= 1
    assert db.session.query(Notification).filter_by(category='error').count() >= 1


def test_notify_when_green_does_nothing(db_session, admin_user):
    from app.backup.alerts import notify_if_stale
    from app.notifications.models import Notification
    db.session.add(BackupRun(triggered_by='cli', status='success',
                             verified_at=ph_now(), created_at=ph_now()))
    db.session.commit()
    assert notify_if_stale() == 0
    assert db.session.query(Notification).count() == 0
