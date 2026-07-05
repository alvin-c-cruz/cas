"""Task 5 — run_backup orchestration: verified-landed success, fail-closed,
concurrency lock, plaintext cleanup."""
import glob
import os
import sqlite3
import tempfile

import pytest

from app import db
from app.backup.crypto import StaticKeyProvider
from app.backup.models import BackupRun
from app.backup.service import run_backup, BackupLocked
from app.backup.storage import LocalStorage

KP = StaticKeyProvider(b'0' * 32)


def _make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()


def _cfg(tmp):
    return {"BACKUP_ENABLED": True, "BACKUP_STORAGE": "local",
            "BACKUP_LOCAL_DIR": str(tmp / "store"), "BACKUP_LOCK_TIMEOUT_MIN": 15}


def _empty(p):
    return not os.path.exists(p) or os.listdir(p) == []


def test_happy_path_verified_success(db_session, tmp_path):
    src = tmp_path / "src.db"
    _make_db(str(src))
    store = LocalStorage(str(tmp_path / "store"))
    run = run_backup('cli', 'admin', storage=store, source_db_path=str(src),
                     key_provider=KP, config=_cfg(tmp_path))
    assert run.status == 'success'
    assert run.verified_at is not None
    assert run.db_plaintext_sha256 and run.manifest_sha256 and run.key_id
    names = [o.name for o in store.list()]
    assert any(n.endswith('.db.enc') for n in names)
    assert any(n.endswith('.manifest.json') for n in names)


def test_missing_key_fail_closed(db_session, tmp_path):
    src = tmp_path / "src.db"
    _make_db(str(src))
    store = LocalStorage(str(tmp_path / "s"))
    run = run_backup('cli', 'admin', storage=store, source_db_path=str(src),
                     key_provider=None, config=_cfg(tmp_path))
    assert run.status == 'failed'
    assert 'key' in (run.error_message or '').lower()
    assert _empty(tmp_path / "s")  # nothing uploaded


def test_integrity_failure_aborts(db_session, tmp_path, monkeypatch):
    src = tmp_path / "src.db"
    _make_db(str(src))
    monkeypatch.setattr('app.backup.service._integrity_ok', lambda p: False)
    store = LocalStorage(str(tmp_path / "s"))
    run = run_backup('cli', 'admin', storage=store, source_db_path=str(src),
                     key_provider=KP, config=_cfg(tmp_path))
    assert run.status == 'failed'
    assert _empty(tmp_path / "s")


def test_verify_mismatch_marks_partial(db_session, tmp_path):
    class BadStore(LocalStorage):
        def stat(self, ref):
            m = super().stat(ref)
            m.checksum = 'deadbeef'
            return m
    src = tmp_path / "src.db"
    _make_db(str(src))
    run = run_backup('cli', 'admin', storage=BadStore(str(tmp_path / "s")),
                     source_db_path=str(src), key_provider=KP, config=_cfg(tmp_path))
    assert run.status == 'partial'
    assert run.verified_at is None


def test_concurrency_lock(db_session, tmp_path):
    db.session.add(BackupRun(triggered_by='cli', status='running', actor='x'))
    db.session.commit()
    with pytest.raises(BackupLocked):
        run_backup('cli', 'admin', storage=LocalStorage(str(tmp_path / "s")),
                   source_db_path=str(tmp_path / "src.db"), key_provider=KP, config=_cfg(tmp_path))


def test_audit_row_written(db_session, tmp_path):
    from app.audit.models import AuditLog
    src = tmp_path / "src.db"
    _make_db(str(src))
    run_backup('cli', 'admin', storage=LocalStorage(str(tmp_path / "s")),
               source_db_path=str(src), key_provider=KP, config=_cfg(tmp_path))
    assert db.session.query(AuditLog).filter_by(module='backup').count() >= 1


def test_verify_latest_ok(db_session, tmp_path):
    from app.backup.service import verify_latest
    src = tmp_path / "src.db"
    _make_db(str(src))
    store = LocalStorage(str(tmp_path / "store"))
    run_backup('cli', 'admin', storage=store, source_db_path=str(src),
               key_provider=KP, config=_cfg(tmp_path))
    res = verify_latest(storage=store, key_provider=KP, config=_cfg(tmp_path))
    assert res['ok'] is True
    assert res['checks']['integrity'] and res['checks']['sha256_match']


def test_verify_latest_no_backup(db_session, tmp_path):
    from app.backup.service import verify_latest
    res = verify_latest(storage=LocalStorage(str(tmp_path / "store")), key_provider=KP,
                        config=_cfg(tmp_path))
    assert res['ok'] is False and res['checks']['has_backup'] is False


def test_no_plaintext_left_on_disk(db_session, tmp_path):
    src = tmp_path / "src.db"
    _make_db(str(src))
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), 'casbk-*')))
    run_backup('cli', 'admin', storage=LocalStorage(str(tmp_path / "s")),
               source_db_path=str(src), key_provider=KP, config=_cfg(tmp_path))
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), 'casbk-*')))
    assert after == before  # work dir (plaintext snapshot + temp) shredded and removed
