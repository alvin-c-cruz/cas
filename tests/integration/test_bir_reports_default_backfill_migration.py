"""Migration-level regression guard for the bir_reports default-off backfill.

MODULE_REGISTRY's 'bir_reports' entry flipped default_enabled from True to False
(chore/bir-reports-default-off) so every optional module is now uniformly off by
default for a brand-new install. Because CAS is deployed to real, already-running
client instances that never had a reason to write an explicit
'module_enabled:bir_reports' override (it was already on), a hand-written data
migration (migrations/versions/bir_bkoff1_backfill_bir_reports_enabled.py) backfills
that override for any database that already has users at migration time, and does
nothing for a genuinely fresh install (0 users).

Per this project's own hard-won lesson (memory `migration-verify-on-real-db-copy`),
a conftest.py/create_all() unit test cannot prove migration/batch-mode behavior --
it builds today's model, not the migration history. So this test drives the REAL
`flask db upgrade` CLI (via subprocess, same interpreter as the running test
process) against real, throwaway on-disk sqlite files, exercising the actual
Alembic upgrade chain end to end, and inspects the resulting database directly.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_flask_db_upgrade(db_path):
    """Run `flask db upgrade` to head against db_path (sqlite file), return CompletedProcess."""
    env = os.environ.copy()
    env['FLASK_APP'] = 'flask_app.py'
    env['FLASK_ENV'] = 'development'
    env.setdefault('SECRET_KEY', 'test-secret-key-for-migration-verification')
    # Absolute Windows path -> sqlite:///C:/... (three slashes, drive letter follows)
    env['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + str(db_path).replace('\\', '/')
    result = subprocess.run(
        [sys.executable, '-m', 'flask', 'db', 'upgrade'],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    return result


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture
def real_db_copy_no_override(tmp_path):
    """A copy of the real demo DB (has users -- an already-used, live-like install),
    with any pre-existing 'module_enabled:bir_reports' override row stripped so it
    reproduces the exact target scenario: a live install that never had to toggle a
    switch that was already in the position it wanted."""
    source = REPO_ROOT.parent / 'cas' / 'instance' / 'cas.db'
    if not source.exists():
        pytest.skip(f'reference demo DB not found at {source}')
    dest = tmp_path / 'live_no_override.db'
    shutil.copy(str(source), str(dest))
    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("DELETE FROM app_settings WHERE key = 'module_enabled:bir_reports'")
        conn.commit()
    finally:
        conn.close()
    return dest


def test_live_install_backfills_bir_reports_enabled(real_db_copy_no_override):
    """A pre-existing DB with real users and NO prior override -> migration inserts
    module_enabled:bir_reports='1' so BIR Reports does not silently disappear."""
    db_path = real_db_copy_no_override
    user_count_before = _query(db_path, 'SELECT COUNT(*) FROM users')[0][0]
    assert user_count_before > 0, 'fixture must represent an already-used install'
    assert _query(db_path,
                  "SELECT * FROM app_settings WHERE key='module_enabled:bir_reports'") == []

    result = _run_flask_db_upgrade(db_path)
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    rows = _query(db_path,
                  "SELECT value, updated_by FROM app_settings WHERE key='module_enabled:bir_reports'")
    assert rows == [('1', 'system_migration')]


def test_live_install_does_not_clobber_existing_override(real_db_copy_no_override):
    """If a client somehow already had an explicit override (any value), the backfill
    must not clobber it -- idempotent/defensive per the migration's own contract."""
    db_path = real_db_copy_no_override
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES (?, ?, ?)",
            ('module_enabled:bir_reports', '0', 'admin'))
        conn.commit()
    finally:
        conn.close()

    result = _run_flask_db_upgrade(db_path)
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    rows = _query(db_path,
                  "SELECT value, updated_by FROM app_settings WHERE key='module_enabled:bir_reports'")
    assert rows == [('0', 'admin')]   # untouched


def test_fresh_install_from_base_does_not_backfill(tmp_path):
    """A genuinely fresh install applying the WHOLE migration chain from base to head
    today has zero users when this migration runs, so it must NOT insert an override
    -- the new default_enabled=False on MODULE_REGISTRY applies naturally."""
    db_path = tmp_path / 'fresh.db'
    assert not db_path.exists()

    result = _run_flask_db_upgrade(db_path)
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    assert _query(db_path, 'SELECT COUNT(*) FROM users')[0][0] == 0
    assert _query(db_path,
                  "SELECT * FROM app_settings WHERE key='module_enabled:bir_reports'") == []

    # Same fallback logic as app.users.module_access.module_enabled(): no override row
    # + registry default_enabled=False -> resolves disabled for a fresh install.
    from app.users.module_access import MODULE_REGISTRY
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'bir_reports')
    assert entry['default_enabled'] is False
