"""rrmulti_0001 drops receiving_reports.purchase_order_id and makes vendor_id NOT NULL.

Built through the REAL migration chain in a subprocess, not conftest's create_all():
create_all builds today's MODEL, not the migration history, so it structurally cannot
prove a constraint change. Batch mode reflects the existing schema and silently
preserves old constraints unless they are explicitly dropped -- a test built from the
model goes green while the real migrated database still enforces the old rule. Same
discipline as test_stock_movement_date_migration.py.
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

CAS_ROOT = pathlib.Path(__file__).resolve().parents[2]

PRE = 'stkdate_0001'          # the revision immediately before this one


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


def _run_expecting_failure(args, db_path):
    result = subprocess.run(args, cwd=CAS_ROOT, env=_env(db_path),
                            capture_output=True, text=True)
    assert result.returncode != 0, (
        'the migration was expected to refuse, but it exited 0\n--- stdout ---\n%s'
        % result.stdout)
    return result.stdout + result.stderr


def _upgrade(db_path, target=None):
    args = [sys.executable, '-m', 'flask', 'db', 'upgrade']
    if target:
        args.append(target)
    return _run(args, db_path)


def _cols(db_path, table):
    con = sqlite3.connect(db_path)
    try:
        return {r[1]: r for r in con.execute('PRAGMA table_info(%s)' % table)}
    finally:
        con.close()


def _indexes(db_path, table):
    con = sqlite3.connect(db_path)
    try:
        return {r[1] for r in con.execute('PRAGMA index_list(%s)' % table)}
    finally:
        con.close()


def _fresh_at_pre(tmp_path, name):
    """A database built by the real chain, stopped one revision before this one."""
    db_path = tmp_path / name
    db_path.touch()
    _upgrade(db_path, PRE)
    return db_path


def _po(con, po_id, number, vendor_id):
    con.execute(
        "INSERT INTO purchase_orders (id, po_number, vendor_id, status, created_at,"
        " updated_at) VALUES (?, ?, ?, 'approved', '2026-07-11 09:00:00',"
        " '2026-07-11 09:00:00')", (po_id, number, vendor_id))


def _poi(con, poi_id, po_id, line_number):
    con.execute(
        "INSERT INTO purchase_order_items (id, purchase_order_id, line_number,"
        " description, quantity, unit_price) VALUES (?, ?, ?, 'Cement', 100, 10)",
        (poi_id, po_id, line_number))


def _rr(con, rr_id, number, header_po_id, vendor_id):
    con.execute(
        "INSERT INTO receiving_reports (id, rr_number, receipt_date, purchase_order_id,"
        " vendor_id, vendor_name, status, created_at, updated_at, row_version)"
        " VALUES (?, ?, '2026-07-11', ?, ?, 'Acme', 'approved',"
        " '2026-07-11 09:00:00', '2026-07-11 09:00:00', 1)",
        (rr_id, number, header_po_id, vendor_id))


def _rr_item(con, item_id, rr_id, line_number, poi_id):
    con.execute(
        "INSERT INTO receiving_report_items (id, receiving_report_id, line_number,"
        " purchase_order_item_id, received_quantity) VALUES (?, ?, ?, ?, 5)",
        (item_id, rr_id, line_number, poi_id))


class TestSchema:

    def test_upgrade_drops_the_header_column_and_tightens_vendor_id(self, tmp_path):
        db_path = tmp_path / 'rrmulti-schema.db'
        db_path.touch()
        _upgrade(db_path)

        cols = _cols(db_path, 'receiving_reports')
        assert 'purchase_order_id' not in cols, 'the header column was not dropped'
        assert 'vendor_id' in cols, 'vendor_id must survive -- it is the new header key'
        # PRAGMA table_info notnull flag is index 3.
        assert cols['vendor_id'][3] == 1, 'vendor_id must be NOT NULL'

        idx = _indexes(db_path, 'receiving_reports')
        assert 'ix_receiving_reports_purchase_order_id' not in idx, (
            'the dropped column left its index behind')
        # CONTROL: the table rebuild must not take the surviving indexes with it.
        assert 'ix_receiving_reports_vendor_id' in idx
        assert 'ix_receiving_reports_status' in idx
        assert 'ix_receiving_reports_rr_number' in idx

    def test_the_line_level_po_link_is_untouched(self, tmp_path):
        """CONTROL. The column being dropped shares its name with the LINE's link on
        purchase_order_items -- a table-blind DROP would take that one too."""
        db_path = tmp_path / 'rrmulti-lines.db'
        db_path.touch()
        _upgrade(db_path)

        assert 'purchase_order_id' in _cols(db_path, 'purchase_order_items')
        assert 'purchase_order_item_id' in _cols(db_path, 'receiving_report_items')


class TestBackfill:

    def test_a_null_vendor_is_filled_from_the_header_po_and_others_are_left_alone(
            self, tmp_path):
        """The backfill must reach a NULL, and must not overwrite a vendor that is
        already set -- even when the header PO disagrees with it.

        RR-2 is the control on the `WHERE vendor_id IS NULL` clause: its own vendor
        (900) differs from its header PO's (901), so dropping that clause silently
        rewrites it. Both rows are non-NULL afterwards, so a bare "no NULLs remain"
        assertion cannot tell the two apart.
        """
        db_path = _fresh_at_pre(tmp_path, 'rrmulti-backfill.db')

        con = sqlite3.connect(db_path)
        _po(con, 1, 'PO-A', vendor_id=800)
        _po(con, 2, 'PO-B', vendor_id=901)
        _rr(con, 1, 'RR-0001', header_po_id=1, vendor_id=None)   # to be backfilled
        _rr(con, 2, 'RR-0002', header_po_id=2, vendor_id=900)    # already set: keep 900
        con.commit()
        con.close()

        _upgrade(db_path)

        con = sqlite3.connect(db_path)
        try:
            rows = dict(con.execute(
                'SELECT rr_number, vendor_id FROM receiving_reports').fetchall())
            nulls = con.execute(
                'SELECT COUNT(*) FROM receiving_reports WHERE vendor_id IS NULL'
            ).fetchone()[0]
        finally:
            con.close()

        assert rows['RR-0001'] == 800, 'vendor_id was not backfilled from the header PO'
        assert rows['RR-0002'] == 900, (
            "an already-set vendor_id was overwritten -- the backfill must only touch NULLs")
        assert nulls == 0, 'vendor_id is NOT NULL but some rows are still empty'

    def test_upgrade_refuses_by_name_when_the_header_po_has_no_vendor_either(
            self, tmp_path):
        """purchase_orders.vendor_id is itself nullable, so the backfill subquery can
        return NULL. The migration must stop and name the receipt rather than let the
        ALTER raise an opaque IntegrityError on a client's live database."""
        db_path = _fresh_at_pre(tmp_path, 'rrmulti-refuse.db')

        con = sqlite3.connect(db_path)
        _po(con, 1, 'PO-NOVENDOR', vendor_id=None)
        _rr(con, 1, 'RR-ORPHAN-01', header_po_id=1, vendor_id=None)
        con.commit()
        con.close()

        output = _run_expecting_failure(
            [sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)

        assert 'RR-ORPHAN-01' in output, (
            'the refusal must name the offending receipt, not just fail')
        # And it must not have half-applied: the column is still there.
        assert 'purchase_order_id' in _cols(db_path, 'receiving_reports')


class TestDowngrade:

    def test_downgrade_repopulates_from_the_first_line_then_upgrade_round_trips(
            self, tmp_path):
        """A downgrade nobody executes is not a downgrade.

        The receipt draws on TWO purchase orders, line 1 from PO-B and line 2 from
        PO-A, so "the first line's PO" is the only answer that is neither the last
        line's nor the lowest id -- a `[-1]` or a MIN(po id) both answer PO-A.
        """
        db_path = _fresh_at_pre(tmp_path, 'rrmulti-roundtrip.db')

        con = sqlite3.connect(db_path)
        _po(con, 1, 'PO-A', vendor_id=800)
        _po(con, 2, 'PO-B', vendor_id=800)
        _poi(con, 11, po_id=1, line_number=1)
        _poi(con, 22, po_id=2, line_number=1)
        _rr(con, 1, 'RR-RT-0001', header_po_id=1, vendor_id=800)
        _rr_item(con, 101, rr_id=1, line_number=1, poi_id=22)   # PO-B first
        _rr_item(con, 102, rr_id=1, line_number=2, poi_id=11)   # PO-A second
        _rr(con, 2, 'RR-RT-LINELESS', header_po_id=1, vendor_id=800)   # no lines at all
        con.commit()
        con.close()

        _upgrade(db_path)
        assert 'purchase_order_id' not in _cols(db_path, 'receiving_reports')

        _run([sys.executable, '-m', 'flask', 'db', 'downgrade', PRE], db_path)

        cols = _cols(db_path, 'receiving_reports')
        assert 'purchase_order_id' in cols, 'downgrade did not restore the column'
        assert cols['vendor_id'][3] == 0, 'downgrade must relax vendor_id back to nullable'
        assert 'ix_receiving_reports_purchase_order_id' in _indexes(
            db_path, 'receiving_reports'), 'downgrade did not restore the index'

        con = sqlite3.connect(db_path)
        try:
            rows = dict(con.execute(
                'SELECT rr_number, purchase_order_id FROM receiving_reports').fetchall())
        finally:
            con.close()
        assert rows['RR-RT-0001'] == 2, (
            'downgrade must repopulate from the FIRST line by line_number (PO-B, id 2)')
        assert rows['RR-RT-LINELESS'] is None, (
            'a receipt with no lines has no purchase order to name')

        # ... and back up again, on the very database the downgrade produced.
        _upgrade(db_path)
        cols = _cols(db_path, 'receiving_reports')
        assert 'purchase_order_id' not in cols
        assert cols['vendor_id'][3] == 1
