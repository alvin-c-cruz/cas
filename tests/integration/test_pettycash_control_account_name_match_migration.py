"""Migration-level regression guard for the petty-cash control-account name-match fix.

Two prior backfill migrations (3ddfe9e60632 short/over, 914f97cdfb0e due-to-custodian)
auto-assign a control-account setting by matching a hardcoded candidate account CODE
only, never checking the matched account's NAME. On construction_coa.py's own chart,
code 20503 is "Current Portion of Long-Term Debt" and code 50303 is "Loss on Disposal
of Assets" -- both unrelated accounts that happen to sit ahead of the chart's real
20105/50304 "Due to Petty Cash Custodian"/"Cash Short/Over" codes in the migrations'
candidate lists, so the buggy migrations always match the WRONG account first. This
was confirmed live via /ui-test on Zhiyuan's real backup (docs/bug-reports/
2026-07-19-pettycash-backfill-wrong-control-account.md).

A new corrective migration re-derives both settings by account NAME instead of code,
touching only rows the two original migrations themselves inserted
(updated_by='migration') -- never a value an accountant deliberately set.

Per this project's own hard-won lesson (memory `migration-verify-on-real-db-copy`), a
conftest.py/create_all() unit test cannot prove migration/batch-mode behavior -- it
builds today's model, not the migration history. So this test drives the REAL
`flask db upgrade` CLI against real, throwaway on-disk sqlite files, exercising the
actual Alembic upgrade chain end to end, and inspects the resulting database directly.
Mirrors tests/integration/test_bir_reports_default_backfill_migration.py's pattern.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]

# Right before the two original petty-cash control-account backfill migrations run
# (caef66b747dd's own down_revision) -- the accounts table exists here, so a chart's
# accounts can be injected before either buggy migration executes.
_PRE_PETTYCASH_REVISION = 'ffc3e66c04c0'


def _run_flask_db(db_path, *args):
    env = os.environ.copy()
    env['FLASK_APP'] = 'flask_app.py'
    env['FLASK_ENV'] = 'development'
    env.setdefault('SECRET_KEY', 'test-secret-key-for-migration-verification')
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


def _insert_account(db_path, code, name, account_type='Liability', normal_balance='credit'):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (code, name, account_type, normal_balance))
        conn.commit()
    finally:
        conn.close()


def _insert_setting(db_path, key, value, updated_by):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES (?, ?, ?)",
            (key, value, updated_by))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_at_pre_pettycash_revision(tmp_path):
    db_path = tmp_path / 'pre_pettycash.db'
    assert not db_path.exists()
    result = _run_flask_db(db_path, 'upgrade', _PRE_PETTYCASH_REVISION)
    assert result.returncode == 0, (
        f'flask db upgrade {_PRE_PETTYCASH_REVISION} failed:\n{result.stdout}\n{result.stderr}')
    return db_path


def test_construction_chart_collision_gets_corrected(db_at_pre_pettycash_revision):
    """construction_coa.py's own numbering: 20503/50303 exist but mean something else;
    the REAL due-to-custodian/short-over accounts sit at 20105/50304. The original
    migrations' candidate-code loop matches 20503/50303 first (wrong); the corrective
    migration must re-point both settings at the correctly-NAMED accounts instead."""
    db_path = db_at_pre_pettycash_revision
    _insert_account(db_path, '20503', 'Current Portion of Long-Term Debt')
    _insert_account(db_path, '20105', 'Due to Petty Cash Custodian')
    _insert_account(db_path, '50303', 'Loss on Disposal of Assets', account_type='Other Expense', normal_balance='debit')
    _insert_account(db_path, '50304', 'Cash Short/Over', account_type='Other Expense', normal_balance='debit')

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    due_to = _query(db_path, "SELECT value FROM app_settings WHERE key='petty_cash_due_to_custodian_account_code'")
    short_over = _query(db_path, "SELECT value FROM app_settings WHERE key='petty_cash_short_over_account_code'")
    assert due_to == [('20105',)], f'expected due-to-custodian corrected to 20105, got {due_to}'
    assert short_over == [('50304',)], f'expected short/over corrected to 50304, got {short_over}'


def test_no_correctly_named_account_leaves_unassigned(db_at_pre_pettycash_revision):
    """Zhiyuan's real scenario: 20503/50303 exist (as unrelated accounts) but NO
    account anywhere on the chart is actually named 'Due to Petty Cash Custodian' or
    'Cash Short/Over'. The setting must end up fail-closed (unassigned), never wrongly
    pointed at the code-colliding account."""
    db_path = db_at_pre_pettycash_revision
    _insert_account(db_path, '20503', 'Current Portion of Long-Term Debt')
    _insert_account(db_path, '50303', 'Loss on Disposal of Assets', account_type='Other Expense', normal_balance='debit')

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    due_to = _query(db_path, "SELECT * FROM app_settings WHERE key='petty_cash_due_to_custodian_account_code'")
    short_over = _query(db_path, "SELECT * FROM app_settings WHERE key='petty_cash_short_over_account_code'")
    assert due_to == [], f'expected unassigned (fail-closed), got {due_to}'
    assert short_over == [], f'expected unassigned (fail-closed), got {short_over}'


def test_seed_data_chart_no_collision_stays_correct(db_at_pre_pettycash_revision):
    """seed_data.py's own numbering has no collision -- 20503/50303 ARE correctly the
    due-to-custodian/short-over accounts. The corrective migration must be a no-op
    here (still ends up pointing at 20503/50303)."""
    db_path = db_at_pre_pettycash_revision
    _insert_account(db_path, '20503', 'Due to Petty Cash Custodian')
    _insert_account(db_path, '50303', 'Cash Short/Over', account_type='Expense', normal_balance='debit')

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    due_to = _query(db_path, "SELECT value FROM app_settings WHERE key='petty_cash_due_to_custodian_account_code'")
    short_over = _query(db_path, "SELECT value FROM app_settings WHERE key='petty_cash_short_over_account_code'")
    assert due_to == [('20503',)]
    assert short_over == [('50303',)]


def test_accountant_manual_assignment_not_overwritten(db_at_pre_pettycash_revision):
    """If a human already assigned a value (updated_by != 'migration') by the time the
    corrective migration runs -- e.g. an accountant fixed it by hand via Company
    Settings before this upgrade ships -- the corrective migration must leave it alone,
    even if a correctly-named account also exists and would otherwise suggest a
    different code."""
    db_path = db_at_pre_pettycash_revision
    _insert_account(db_path, '20503', 'Current Portion of Long-Term Debt')
    _insert_account(db_path, '20105', 'Due to Petty Cash Custodian')
    _insert_setting(db_path, 'petty_cash_due_to_custodian_account_code', '20503', 'admin')

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    due_to = _query(db_path, "SELECT value, updated_by FROM app_settings WHERE key='petty_cash_due_to_custodian_account_code'")
    assert due_to == [('20503', 'admin')], f'accountant-assigned value must be untouched, got {due_to}'


def test_fresh_install_from_base_leaves_unassigned(tmp_path):
    """A genuinely fresh install (whole chain from base to head, zero accounts) must
    not error and must leave both settings unassigned."""
    db_path = tmp_path / 'fresh.db'
    assert not db_path.exists()

    result = _run_flask_db(db_path, 'upgrade')
    assert result.returncode == 0, f'flask db upgrade failed:\n{result.stdout}\n{result.stderr}'

    due_to = _query(db_path, "SELECT * FROM app_settings WHERE key='petty_cash_due_to_custodian_account_code'")
    short_over = _query(db_path, "SELECT * FROM app_settings WHERE key='petty_cash_short_over_account_code'")
    assert due_to == []
    assert short_over == []
