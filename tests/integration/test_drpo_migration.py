"""B2 A, migration drpo_0001: delivery_receipts.customer_po_number, filled for existing DRs from their order's PO.

Until B2 the DR pre-printed print and the invoice's DR billing read the PO from the DR's sales order. From drpo_0001 they
read the DR's own PO, so every existing DR against an order takes its order's PO in the migration and prints as before.
A DR without an order, or whose order has no PO (or a blank one), stays empty.

Built the way test_po_rev0_backfill.py builds its database: an empty SQLite file under the test's tmp directory, the REAL
migration history up to riclay_0001, rows written with sqlite3, then `flask db upgrade drpo_0001`. Its guard refuses
any database outside the tmp directory (.env points at a client's copy).
"""
import sqlite3
import sys

import pytest

from tests.integration.test_po_rev0_backfill import _run

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _insert(con, table, **values):
    """A row with `values`, and a plain filler in every other NOT NULL column without a default."""
    row = dict(values)
    for _, name, col_type, notnull, default, pk in con.execute(f'PRAGMA table_info({table})'):
        if pk or not notnull or default is not None or name in row:
            continue
        t = (col_type or '').upper()
        row[name] = (1 if 'INT' in t or 'BOOL' in t else 0 if ('NUMERIC' in t or 'DECIMAL' in t or 'FLOAT' in t)
                     else '2026-11-01 00:00:00' if 'DATETIME' in t else '2026-11-01' if 'DATE' in t else 'x')
    cols = ', '.join(row)
    con.execute(f'INSERT INTO {table} ({cols}) VALUES ({", ".join("?" * len(row))})', list(row.values()))


@pytest.fixture(scope='module')
def migrated(tmp_path_factory):
    directory = tmp_path_factory.mktemp('drpo')
    db_path = directory / 'drpo.db'
    db_path.touch()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'riclay_0001'], db_path, directory)
    con = sqlite3.connect(db_path)
    _insert(con, 'sales_orders', id=1, so_number='SO-1', customer_po_number='PO-16674')
    _insert(con, 'sales_orders', id=2, so_number='SO-2', customer_po_number=None)
    _insert(con, 'sales_orders', id=3, so_number='SO-3', customer_po_number='  ')
    _insert(con, 'delivery_receipts', id=1, dr_number='0264', sales_order_id=1)
    _insert(con, 'delivery_receipts', id=2, dr_number='0265', sales_order_id=2)
    _insert(con, 'delivery_receipts', id=3, dr_number='0266', sales_order_id=None)
    _insert(con, 'delivery_receipts', id=4, dr_number='0267', sales_order_id=3)
    con.commit()
    con.close()
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'drpo_0001'], db_path, directory)
    return db_path, directory


def _pos(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute('SELECT dr_number, customer_po_number FROM delivery_receipts ORDER BY id').fetchall()
    finally:
        con.close()


def test_existing_drs_take_their_orders_po(migrated):
    db_path, _ = migrated
    assert _pos(db_path) == [('0264', 'PO-16674'), ('0265', None), ('0266', None), ('0267', None)]


def test_the_column_is_a_short_text(migrated):
    db_path, _ = migrated
    con = sqlite3.connect(db_path)
    cols = {name: (col_type, notnull) for _, name, col_type, notnull, _, _ in
            con.execute('PRAGMA table_info(delivery_receipts)')}
    con.close()
    assert cols['customer_po_number'] == ('VARCHAR(100)', 0)


def test_it_goes_back_down_cleanly(migrated, tmp_path):
    import shutil
    db_path, _ = migrated
    copy = tmp_path / 'down.db'
    shutil.copy(db_path, copy)
    _run([sys.executable, '-m', 'flask', 'db', 'downgrade', 'riclay_0001'], copy, tmp_path)
    con = sqlite3.connect(copy)
    cols = [r[1] for r in con.execute('PRAGMA table_info(delivery_receipts)')]
    rows = con.execute('SELECT dr_number, sales_order_id FROM delivery_receipts ORDER BY id').fetchall()
    con.close()
    assert 'customer_po_number' not in cols
    assert rows == [('0264', 1), ('0265', 2), ('0266', None), ('0267', 3)]
