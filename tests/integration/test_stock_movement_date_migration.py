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


def test_preexisting_opening_layer_is_redated_to_sentinel(tmp_path):
    """A pre-existing opening-balance layer (source_movement_id IS NULL,
    original_qty > 0), bootstrapped before this branch, was written with
    ph_now() -- the pre-existing normalisation line alone would re-date it to
    midnight of that bootstrap date, not the sentinel, leaving it exposed to
    exactly the mis-ordering the code fix closes for new rows (see
    bootstrap_opening_layer_if_needed's docstring). The upgrade must move it
    to the datetime.min sentinel instead.

    A virgin zero-cost DEFICIT layer (also source_movement_id IS NULL, but
    original_qty == 0 -- see fifo_plan_consume's deficit_layer fallback) must
    NOT be moved: it isn't opening stock, and moving it to the sentinel would
    make it wrongly out-sort every other layer.
    """
    db_path = tmp_path / 'stkdate-opening-layer.db'
    db_path.touch()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'pralloc_0001'], db_path)

    # Distinct product_id/branch_id -- uq_stock_cost_layers_opening_layer allows
    # only ONE source_movement_id-IS-NULL row per product/branch pair.
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO stock_cost_layers (id, product_id, branch_id, original_qty,"
        " remaining_qty, unit_cost, received_at, source_movement_id)"
        " VALUES (1, 1, 1, 5.0000, 5.0000, 2.00, '2026-02-14 09:30:00', NULL)")
    con.execute(
        "INSERT INTO stock_cost_layers (id, product_id, branch_id, original_qty,"
        " remaining_qty, unit_cost, received_at, source_movement_id)"
        " VALUES (2, 2, 1, 0.0000, -3.0000, 0.00, '2026-02-20 11:00:00', NULL)")
    con.commit()
    con.close()

    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)

    con = sqlite3.connect(db_path)
    try:
        opening = con.execute(
            'SELECT received_at FROM stock_cost_layers WHERE id = 1').fetchone()[0]
        deficit = con.execute(
            'SELECT received_at FROM stock_cost_layers WHERE id = 2').fetchone()[0]
    finally:
        con.close()
    assert str(opening).startswith('0001-01-01'), (
        'the pre-existing opening layer (original_qty > 0) must be re-dated to the sentinel')
    assert not str(deficit).startswith('0001-01-01'), (
        'a virgin zero-cost deficit layer (original_qty == 0) must NOT be moved to the sentinel')
    assert str(deficit).startswith('2026-02-20'), (
        'the deficit layer only gets the plain midnight normalisation, not the sentinel move')
