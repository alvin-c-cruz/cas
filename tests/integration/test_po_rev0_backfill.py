"""The backfill migration gives every pre-existing non-draft PO a Rev 0 that the
viewer can render, and marks it honestly as reconstructed."""
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.purchase_orders.models import PurchaseOrder

CAS_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_backfill_on_a_real_db_copy(tmp_path):
    """Runs the REAL migration against a COPY of a real database.

    A create_all() fixture builds today's model, not the migration history, so it
    cannot prove a migration works. This must be the real chain on real rows.
    """
    src = CAS_ROOT / 'instance' / 'philgen.db'
    if not src.exists():
        pytest.skip('no real DB available to copy')
    dst = tmp_path / 'backfill-check.db'
    shutil.copy(src, dst)

    # Make the fixture deterministic regardless of what the real DB holds:
    # everything draft, then exactly one approved.
    con = sqlite3.connect(dst)
    con.execute("UPDATE purchase_orders SET status='draft'")
    con.execute("UPDATE purchase_orders SET status='approved' "
                "WHERE id = (SELECT MIN(id) FROM purchase_orders)")
    con.commit()
    con.close()

    env = {'SQLALCHEMY_DATABASE_URI': f'sqlite:///{dst}', 'FLASK_APP': 'flask_app.py'}
    import os
    env = {**os.environ, **env}
    result = subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'],
                            cwd=CAS_ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(dst)
    rows = con.execute(
        "SELECT revision_number, reason, snapshot_json FROM document_revisions "
        "WHERE document_type='purchase_orders'").fetchall()
    con.close()

    assert len(rows) == 1
    number, reason, snapshot = rows[0]
    assert number == 0
    assert 'reconstructed' in reason.lower(), 'a backfilled Rev 0 must not claim to be an original capture'

    snap = json.loads(snapshot)
    for key in PurchaseOrder.SNAPSHOT_HEADER_FIELDS:
        assert key in snap['header'], f'{key} missing -- the viewer would render a false default'
    assert 'total_amount_display' in snap['header']
    assert snap['lines'], 'lines must be captured, not just the header'
    assert isinstance(snap['lines'][0]['line_id'], int)


@pytest.mark.slow
def test_draft_purchase_orders_are_not_backfilled(tmp_path):
    """Rev 0 means 'as approved'. A draft PO has never been approved, so it gets none."""
    src = CAS_ROOT / 'instance' / 'philgen.db'
    if not src.exists():
        pytest.skip('no real DB available to copy')
    dst = tmp_path / 'backfill-draft.db'
    shutil.copy(src, dst)

    con = sqlite3.connect(dst)
    con.execute("UPDATE purchase_orders SET status='draft'")
    con.commit()
    con.close()

    import os
    env = {**os.environ, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{dst}',
           'FLASK_APP': 'flask_app.py'}
    result = subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'],
                            cwd=CAS_ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(dst)
    count = con.execute("SELECT COUNT(*) FROM document_revisions "
                        "WHERE document_type='purchase_orders'").fetchone()[0]
    con.close()
    assert count == 0
