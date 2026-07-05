"""Task 8 — backup admin views wiring (status page + run button)."""
import base64

import pytest

from app import db
from app.backup.models import BackupRun

pytestmark = [pytest.mark.integration]


def _login(client, user, main_branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def test_status_requires_login(client, db_session):
    resp = client.get('/backup')
    assert resp.status_code == 302  # gated -> redirected to login/dashboard


def test_status_page_loads_for_admin(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.get('/backup')
    assert resp.status_code == 200
    assert b'Backup' in resp.data


def test_run_flashes_not_configured(client, db_session, admin_user, main_branch):
    # BACKUP_ENABLED is False by default -> POST flashes not-configured
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.post('/backup/run', follow_redirects=True)
    assert resp.status_code == 200
    assert b'not configured' in resp.data


def test_run_creates_backuprun_when_configured(client, db_session, admin_user, main_branch,
                                               tmp_path, monkeypatch):
    kf = tmp_path / 'k'
    kf.write_bytes(base64.b64encode(b'0' * 32))
    cfg = client.application.config
    monkeypatch.setitem(cfg, 'BACKUP_ENABLED', True)
    monkeypatch.setitem(cfg, 'BACKUP_STORAGE', 'local')
    monkeypatch.setitem(cfg, 'BACKUP_LOCAL_DIR', str(tmp_path / 'store'))
    monkeypatch.setitem(cfg, 'BACKUP_ENC_KEY', str(kf))
    _login(client, admin_user, main_branch, 'admin123')
    before = db.session.query(BackupRun).count()
    resp = client.post('/backup/run', follow_redirects=True)
    assert resp.status_code == 200
    # a BackupRun row was recorded (source is the :memory: test DB, so the run
    # itself may not 'succeed' here — the wiring is what this asserts)
    assert db.session.query(BackupRun).count() == before + 1
