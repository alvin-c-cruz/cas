"""`prlydrop_0001` drops the dead `print_layouts` table.

An abandoned 2026-07-02 attempt at pre-printed layouts (migrations f826f2cca271,
307cc71c8779), superseded by the app_settings approach and then by the named-layouts
feature, which had to call its tables `named_print_layouts` /
`named_print_layout_device_prefs` because this one squatted the name. Empty on philgen
and ric, mapped by no model, read by no code. Owner, 2026-09-25: drop it.

Real migration history in a subprocess, never create_all(): the point is what the
chain does to a real file.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

CAS_ROOT = Path(__file__).resolve().parents[2]


def _flask(args, db_path, check=True):
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}')
    env.pop('CAS_EXPECT_COMPANY', None)
    return subprocess.run([sys.executable, '-m', 'flask', 'db', *args], cwd=CAS_ROOT, env=env,
                          capture_output=True, text=True, check=check)


def _tables(db_path):
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _indexes(db_path, table):
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,))}
    finally:
        con.close()


def test_upgrade_drops_the_table_and_leaves_the_named_layouts_alone(tmp_path):
    db = tmp_path / 'drop.db'; db.touch()
    _flask(['upgrade', 'cdvpay_0001'], db)
    assert 'print_layouts' in _tables(db), 'anti-vacuity: the table exists before the drop'

    _flask(['upgrade', 'prlydrop_0001'], db)

    tables = _tables(db)
    assert 'print_layouts' not in tables
    assert {'named_print_layouts', 'named_print_layout_device_prefs'} <= tables
    con = sqlite3.connect(db)
    assert con.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    con.close()


def test_upgrade_refuses_if_the_table_is_not_empty(tmp_path):
    """Dead means EMPTY. If some instance ever wrote a row, stop rather than lose it."""
    db = tmp_path / 'drop-refuse.db'; db.touch()
    _flask(['upgrade', 'cdvpay_0001'], db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO print_layouts (voucher_type, active, page_width_mm, page_height_mm) "
                "VALUES ('cdv', 1, 241.3, 279.4)")
    con.commit(); con.close()

    result = _flask(['upgrade', 'prlydrop_0001'], db, check=False)

    assert result.returncode != 0
    assert 'print_layouts is not empty' in result.stderr
    assert 'print_layouts' in _tables(db), 'the refused drop must leave the table in place'


def test_downgrade_recreates_the_table_as_it_was(tmp_path):
    """The schema 307cc71c8779 left behind: same columns, same indexes, same constraints."""
    before = tmp_path / 'before.db'; before.touch()
    _flask(['upgrade', 'cdvpay_0001'], before)
    after = tmp_path / 'after.db'; after.touch()
    _flask(['upgrade', 'prlydrop_0001'], after)
    _flask(['downgrade', 'cdvpay_0001'], after)

    def columns(db):
        con = sqlite3.connect(db)
        try:
            return [(r[1], r[2].upper(), r[3]) for r in con.execute('PRAGMA table_info(print_layouts)')]
        finally:
            con.close()

    assert columns(after) == columns(before)
    assert _indexes(after, 'print_layouts') == _indexes(before, 'print_layouts')
