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

Both tests below build a DB stopped at bir_bkoff1's own down_revision
(prodcat_0002) rather than copying an already-fully-migrated DB (e.g. the real
demo cas.db). Alembic tracks applied revisions and never re-runs one that's
already stamped, so upgrading an already-head DB is a silent no-op for
bir_bkoff1 regardless of what state you poke into it first -- that was the bug
in the previous version of this file: it copied `instance/cas.db` (already at
head), so `flask db upgrade` never actually executed bir_bkoff1's upgrade() at
all, and `test_live_install_does_not_clobber_existing_override` passed
vacuously (nothing could have clobbered the override, because the migration
never ran). Stopping at the pre-backfill revision and injecting state there
(a users row, and for the second test an existing override row) before
completing the upgrade to head is the only way to make bir_bkoff1's upgrade()
genuinely execute under test.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]

# bir_bkoff1's own down_revision (migrations/versions/bir_bkoff1_backfill_bir_reports_enabled.py) --
# the DB must be stopped here so the final `flask db upgrade` to head actually runs bir_bkoff1.
_PRE_BACKFILL_REVISION = 'prodcat_0002'


def _run_flask_db(db_path, *args):
    """Run `flask db <args>` against db_path (sqlite file), return CompletedProcess."""
    env = os.environ.copy()
    env['FLASK_APP'] = 'flask_app.py'
    env['FLASK_ENV'] = 'development'
    env.setdefault('SECRET_KEY', 'test-secret-key-for-migration-verification')
    # Absolute Windows path -> sqlite:///C:/... (three slashes, drive letter follows)
    env['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + str(db_path).replace('\\', '/')
    result = subprocess.run(
        [sys.executable, '-m', 'flask', 'db', *args],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    return result


def _query(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _insert_dummy_user(db_path, username='migration_test_admin'):
    """Insert a minimal, valid `users` row directly via SQL -- simulates 'an admin was
    already bootstrapped' (the migration's own heuristic for 'already-used install')
    without depending on the ORM/app factory mid-chain, at a schema point (users table
    has existed since long before prodcat_0002) that's stable regardless of today's
    full User model."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, full_name, role, "
            "is_active, failed_login_attempts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, f'{username}@test.local', 'x', 'Migration Test User', 'admin', 1, 0))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_at_pre_backfill_revision(tmp_path):
    """A fresh DB migrated up to (not including) bir_bkoff1."""
    db_path = tmp_path / 'pre_backfill.db'
    assert not db_path.exists()
    result = _run_flask_db(db_path, 'upgrade', _PRE_BACKFILL_REVISION)
    assert result.returncode == 0, (
        f'flask db upgrade {_PRE_BACKFILL_REVISION} failed:\n{result.stdout}\n{result.stderr}')
    return db_path


def test_live_install_backfills_bir_reports_enabled(db_at_pre_backfill_revision):
    """A pre-existing DB with real users and NO prior override -> migration inserts
    module_enabled:bir_reports='1' so BIR Reports does not silently disappear."""
    db_path = db_at_pre_backfill_revision
    _insert_dummy_user(db_path)
    assert _query(db_path, 'SELECT COUNT(*) FROM users')[0][0] > 0
    assert _query(db_path,
                  "SELECT * FROM app_settings WHERE key='module_enabled:bir_reports'") == []

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    rows = _query(db_path,
                  "SELECT value, updated_by FROM app_settings WHERE key='module_enabled:bir_reports'")
    assert rows == [('1', 'system_migration')]


def test_live_install_does_not_clobber_existing_override(db_at_pre_backfill_revision):
    """If a client somehow already had an explicit override (any value) by the time
    bir_bkoff1 runs, the backfill must not clobber it -- idempotent/defensive per the
    migration's own contract."""
    db_path = db_at_pre_backfill_revision
    _insert_dummy_user(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES (?, ?, ?)",
            ('module_enabled:bir_reports', '0', 'admin'))
        conn.commit()
    finally:
        conn.close()

    result = _run_flask_db(db_path, 'upgrade')
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

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    assert _query(db_path, 'SELECT COUNT(*) FROM users')[0][0] == 0
    assert _query(db_path,
                  "SELECT * FROM app_settings WHERE key='module_enabled:bir_reports'") == []

    # Same fallback logic as app.users.module_access.module_enabled(): no override row
    # + registry default_enabled=False -> resolves disabled for a fresh install.
    from app.users.module_access import MODULE_REGISTRY
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'bir_reports')
    assert entry['default_enabled'] is False
