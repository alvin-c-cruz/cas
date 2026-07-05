"""Task 3 — BackupRun model."""
from app import db
from app.backup.models import BackupRun


def test_backuprun_defaults(db_session):
    r = BackupRun(triggered_by='manual', actor='admin', status='running')
    db_session.add(r)
    db_session.commit()
    got = db_session.get(BackupRun, r.id)
    assert got.status == 'running'
    assert got.created_at is not None
    assert got.started_at is not None


def test_backuprun_optional_fields_nullable(db_session):
    r = BackupRun(triggered_by='cli', status='failed', error_message='boom')
    db_session.add(r)
    db_session.commit()
    got = db_session.get(BackupRun, r.id)
    assert got.error_message == 'boom'
    assert got.verified_at is None
    assert got.db_plaintext_sha256 is None
