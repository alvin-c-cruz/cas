"""Task 8 — backup CLI commands are registered on the app.

The command logic (run_backup / verify_latest) is fully covered by the service
unit tests; this asserts the CLI wiring."""
import pytest

pytestmark = [pytest.mark.integration]


def test_cli_commands_registered(app):
    assert 'backup-run' in app.cli.commands
    assert 'backup-verify' in app.cli.commands
    assert 'backup-restore' in app.cli.commands
    assert 'backup-mint-token' in app.cli.commands


def test_backup_restore_from_storage(app, db_session, tmp_path, monkeypatch):
    """DR path: restore the newest artifact by listing storage, no BackupRun lookup."""
    import base64
    import sqlite3
    from app.backup.crypto import FileKeyProvider
    from app.backup.service import run_backup
    from app.backup.storage import LocalStorage

    # a real source DB with a known row
    src = tmp_path / "src.db"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()
    keyfile = tmp_path / "k"
    keyfile.write_bytes(base64.b64encode(b'0' * 32))
    store = LocalStorage(str(tmp_path / "store"))

    with app.app_context():
        run_backup('cli', 'admin', storage=store, source_db_path=str(src),
                   key_provider=FileKeyProvider(str(keyfile)),
                   config={'BACKUP_LOCK_TIMEOUT_MIN': 15})

    monkeypatch.setitem(app.config, 'BACKUP_STORAGE', 'local')
    monkeypatch.setitem(app.config, 'BACKUP_LOCAL_DIR', str(tmp_path / "store"))
    monkeypatch.setitem(app.config, 'BACKUP_ENC_KEY', str(keyfile))

    into = str(tmp_path / "restored.db")
    result = app.test_cli_runner().invoke(args=['backup-restore', '--into', into, '--from-storage'])
    assert result.exit_code == 0, result.output

    con = sqlite3.connect(into)
    assert con.execute("SELECT x FROM t").fetchone()[0] == 42
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
