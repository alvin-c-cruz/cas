"""Backup orchestration.

Success == verified-landed (artifact read back from storage with a matching
size + checksum). Fail-closed: any expected failure records a failed/partial
BackupRun and returns it; plaintext snapshots are shredded on every path.
"""
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import timedelta

from flask import current_app

from app import db
from app.utils import ph_now
from app.backup.crypto import encrypt, decrypt, FileKeyProvider
from app.backup.models import BackupRun
from app.backup.storage import get_storage


class BackupLocked(Exception):
    """Raised when another backup run is already in progress."""


def _integrity_ok(path: str) -> bool:
    con = sqlite3.connect(path)
    try:
        rows = con.execute("PRAGMA integrity_check").fetchall()
    finally:
        con.close()
    return rows == [("ok",)]


def _vacuum_into(source_db_path: str, dest_path: str):
    con = sqlite3.connect(source_db_path)
    try:
        con.isolation_level = None  # autocommit; VACUUM cannot run in a transaction
        con.execute("VACUUM INTO ?", (dest_path,))
    finally:
        con.close()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_source(source_db_path):
    if source_db_path:
        return source_db_path
    path = db.engine.url.database
    if not os.path.isabs(path):
        path = os.path.join(current_app.instance_path, path)
    return os.path.abspath(path)


def _acquire_lock(clock, lock_minutes):
    cutoff = (clock() - timedelta(minutes=lock_minutes)).replace(tzinfo=None)
    for stale in BackupRun.query.filter_by(status='running').all():
        started = stale.started_at
        if started is not None and started.tzinfo is not None:
            started = started.replace(tzinfo=None)
        if started is not None and started < cutoff:
            stale.status = 'failed'
            stale.error_message = 'reclaimed: stale running lock'
            stale.finished_at = clock()
        else:
            raise BackupLocked(f"backup already running (run {stale.id})")
    db.session.commit()


def run_backup(triggered_by, actor, *, storage=None, source_db_path=None,
               key_provider=None, clock=ph_now, config=None):
    config = config or {}
    lock_minutes = int(config.get("BACKUP_LOCK_TIMEOUT_MIN", 15))
    _acquire_lock(clock, lock_minutes)

    run = BackupRun(triggered_by=triggered_by, actor=actor, status='running',
                    created_at=clock(), started_at=clock())
    db.session.add(run)
    db.session.commit()
    start = clock()

    workdir = tempfile.mkdtemp(prefix="casbk-")
    snap = os.path.join(workdir, f"{uuid.uuid4().hex}.snap")
    enc_path = os.path.join(workdir, "artifact.enc")
    man_path = os.path.join(workdir, "manifest.json")
    try:
        # fail-closed: key + storage resolve BEFORE any snapshot or upload
        if key_provider is None:
            if config.get("BACKUP_ENC_KEY"):
                key_provider = FileKeyProvider(config["BACKUP_ENC_KEY"])
            else:
                raise ValueError("no encryption key configured (BACKUP_ENC_KEY)")
        storage = storage or get_storage(config)

        _vacuum_into(_resolve_source(source_db_path), snap)
        if not _integrity_ok(snap):
            raise ValueError("integrity_check failed on snapshot")

        run.db_plaintext_sha256 = _sha256(snap)
        run.db_size = os.path.getsize(snap)
        run.key_id, _ = key_provider.current()

        with open(snap, "rb") as fh:
            enc = encrypt(fh.read(), key_provider)
        with open(enc_path, "wb") as fh:
            fh.write(enc)

        stamp = clock().strftime("%Y-%m-%dT%H-%M-%S")
        db_name = f"cas-{stamp}.db.enc"
        db_ref = storage.put(enc_path, db_name)

        # verified-landed: read back size + checksum and require a match
        meta = storage.stat(db_ref)
        if meta.size != os.path.getsize(enc_path) or meta.checksum != _sha256(enc_path):
            run.status = 'partial'
            run.error_message = 'read-back mismatch after upload'
            run.finished_at = clock()
            db.session.commit()
            _audit(run)
            return run

        manifest = {"version": 1, "run_id": run.id,
                    "created_at": run.created_at.isoformat(), "key_id": run.key_id,
                    "db_plaintext_sha256": run.db_plaintext_sha256,
                    "artifacts": {db_name: {"ref": db_ref, "size": meta.size,
                                            "checksum": meta.checksum,
                                            "checksum_algo": meta.checksum_algo}}}
        mbytes = json.dumps(manifest, sort_keys=True).encode()
        with open(man_path, "wb") as fh:
            fh.write(mbytes)
        storage.put(man_path, f"cas-{stamp}.manifest.json")

        run.artifacts = json.dumps(manifest["artifacts"])
        run.manifest_sha256 = hashlib.sha256(mbytes).hexdigest()
        run.status = 'success'
        run.verified_at = clock()
        run.finished_at = clock()
        run.duration_ms = int((clock() - start).total_seconds() * 1000)
        db.session.commit()
        _audit(run)
        return run
    except BackupLocked:
        raise
    except Exception as exc:  # noqa: BLE001 — fail-closed: record, never crash the caller
        db.session.rollback()
        run = db.session.get(BackupRun, run.id)
        run.status = 'failed'
        run.error_message = str(exc)[:1000]
        run.finished_at = clock()
        db.session.commit()
        _audit(run)
        return run
    finally:
        for f in (snap, enc_path, man_path):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


def verify_latest(*, storage=None, key_provider=None, config=None):
    """Shallow restore proof: download latest success -> decrypt -> integrity_check
    -> recompute plaintext sha256 and assert it matches the recorded value."""
    config = config or {}
    storage = storage or get_storage(config)
    if key_provider is None:
        key_provider = FileKeyProvider(config["BACKUP_ENC_KEY"])
    run = (BackupRun.query.filter_by(status='success')
           .order_by(BackupRun.id.desc()).first())
    if run is None:
        return {"ok": False, "run_id": None, "checks": {"has_backup": False}}
    arts = json.loads(run.artifacts)
    db_entry = next(v for k, v in arts.items() if k.endswith(".db.enc"))
    wd = tempfile.mkdtemp(prefix="casvfy-")
    enc = os.path.join(wd, "a.enc")
    dec = os.path.join(wd, "a.db")
    try:
        storage.get(db_entry["ref"], enc)
        with open(enc, "rb") as fh:
            plain = decrypt(fh.read(), key_provider)
        with open(dec, "wb") as fh:
            fh.write(plain)
        integrity = _integrity_ok(dec)
        sha_match = hashlib.sha256(plain).hexdigest() == run.db_plaintext_sha256
        return {"ok": bool(integrity and sha_match), "run_id": run.id,
                "checks": {"has_backup": True, "integrity": integrity,
                           "sha256_match": sha_match}}
    finally:
        for f in (enc, dec):
            if os.path.exists(f):
                os.remove(f)
        try:
            os.rmdir(wd)
        except OSError:
            pass


def _audit(run):
    from app.audit.utils import log_audit
    log_audit(module='backup', action='run', record_id=run.id,
              record_identifier=f"{run.status} {run.created_at:%Y-%m-%d %H:%M}",
              notes=f"actor={run.actor} {run.error_message or ''}".strip())
