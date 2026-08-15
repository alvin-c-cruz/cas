"""stkdate_0001 adds StockMovement.movement_date and backfills it.

Built through the REAL migration chain in a subprocess, not conftest's
create_all(): create_all builds today's model, not the migration history, so it
cannot prove a migration runs. Same discipline as test_po_rev0_backfill.py.
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration]

CAS_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _env(db_path):
    env = dict(os.environ)
    env['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + str(db_path).replace('\\', '/')
    env['FLASK_APP'] = 'flask_app'
    return env


def _run(args, db_path):
    # pytest.fail, never pytest.skip: an unrunnable migration is a FAILURE.
    result = subprocess.run(args, cwd=CAS_ROOT, env=_env(db_path),
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail('%s exited %d\n--- stdout ---\n%s\n--- stderr ---\n%s'
                    % (' '.join(str(a) for a in args), result.returncode,
                       result.stdout, result.stderr))
    return result


def _cols(db_path, table):
    con = sqlite3.connect(db_path)
    try:
        return {r[1]: r for r in con.execute('PRAGMA table_info(%s)' % table)}
    finally:
        con.close()


def test_upgrade_adds_a_not_null_movement_date(tmp_path):
    db_path = tmp_path / 'stkdate.db'
    db_path.touch()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)

    cols = _cols(db_path, 'stock_movements')
    assert 'movement_date' in cols, 'the column was not added'
    # PRAGMA table_info notnull flag is index 3
    assert cols['movement_date'][3] == 1, 'movement_date must be NOT NULL'


def test_backfill_takes_the_date_part_of_created_at(tmp_path):
    """A pre-existing row must land on its posting DATE, not NULL."""
    db_path = tmp_path / 'stkdate-backfill.db'
    db_path.touch()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'pralloc_0001'], db_path)

    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO stock_movements (product_id, branch_id, movement_type, quantity,"
        " unit_cost, balance_qty_after, balance_avg_cost_after, balance_value_after,"
        " created_at) VALUES (1, 1, 'receipt', 5, 2.0, 5, 2.0, 10.0,"
        " '2026-01-09 13:45:00')")
    con.commit()
    con.close()

    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)

    con = sqlite3.connect(db_path)
    try:
        got = con.execute('SELECT movement_date FROM stock_movements').fetchone()[0]
    finally:
        con.close()
    assert str(got).startswith('2026-01-09'), 'backfill did not use the date part of created_at'


def test_downgrade_then_upgrade_round_trips(tmp_path):
    db_path = tmp_path / 'stkdate-roundtrip.db'
    db_path.touch()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)
    _run([sys.executable, '-m', 'flask', 'db', 'downgrade', 'pralloc_0001'], db_path)
    assert 'movement_date' not in _cols(db_path, 'stock_movements')
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)
    assert 'movement_date' in _cols(db_path, 'stock_movements')
