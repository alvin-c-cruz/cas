"""The docrev_0002 backfill gives every pre-existing non-draft PO a Rev 0 that is
BYTE-IDENTICAL to the one the live write_revision() path would have written, and
marks it honestly as reconstructed.

Two design rules this file exists to hold:

1. NOTHING here reads instance/philgen.db. `instance/` is gitignored, so a test
   that skips when it is absent reports success on CI, on a fresh clone and in
   every new worktree -- deleting the migration outright would leave the suite
   green everywhere but one laptop. The fixture below builds its own database:
   an empty SQLite file, `flask db upgrade docrev_0001` for the REAL schema at
   the pre-backfill revision, rows seeded through the REAL ORM, then
   `flask db upgrade` to apply docrev_0002. There is no skip path.

2. The assertions compare VALUES, not key presence. An earlier version asserted
   only that SNAPSHOT_HEADER_FIELDS' keys existed; with `branch_name`,
   `product_code`, `uom_code` and `unit_price_display` deleted from the
   migration it still passed, and with the bool/datetime formatting reverted it
   still passed. The parity test below compares the full parsed JSON -- every
   header key, every line key, every value -- against a Rev 0 written by the
   live path for a field-identical PO, excluding only `po_number` and `line_id`,
   the two values that legitimately cannot match.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

CAS_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.slow

# Seeded through the ORM so the live write_revision()/build_snapshot() path -- not
# a hand-rolled restatement of it -- produces the reference snapshot.
#
#  PO-LIVE-0001     approved + write_revision() -> a real Rev 0, reason NULL.
#                   The migration must LEAVE IT ALONE (duplicate-Rev-0 guard).
#  PO-BACKFILL-0001 field-identical to PO-LIVE-0001 apart from po_number, approved
#                   but with no revision -- the row the migration must reconstruct.
#  PO-DRAFT-0001    identical again but still draft -- must get nothing.
#
# approved_at deliberately has microsecond 0: SQLite always stores 6 fractional
# digits while datetime.isoformat() omits the fraction entirely at microsecond 0,
# so this is the case that catches the migration's datetime conversion drifting.
# vat_override is True so str(bool(1)) ('True') is distinguishable from str(1) ('1').
# reference/notes/description carry both quote characters so the migration's bound
# parameters are exercised on text that would break interpolation.
_SEED_SCRIPT = '''
import sys
sys.path.insert(0, sys.argv[1])

from datetime import date, datetime
from decimal import Decimal

from app import create_app, db

app = create_app('development')
with app.app_context():
    from app.branches.models import Branch
    from app.users.models import User
    from app.vendors.models import Vendor
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.amendments.service import write_revision

    branch = Branch(code='MNL', name='Manila Branch', is_active=True)
    user = User(username='approver', email='approver@example.com',
                password_hash='not-a-real-hash', full_name='Ana Approver',
                role='admin', is_active=True)
    vendor = Vendor(code='V900', name='ACME Trading', is_active=True)
    uom = UnitOfMeasure(code='PCS', name='Pieces', is_active=True)
    product = Product(code='P-001', name='Widget', is_active=True)
    db.session.add_all([branch, user, vendor, uom, product])
    db.session.commit()

    APPROVED_AT = datetime(2026, 8, 9, 12, 0, 0)

    def make_po(number, status):
        po = PurchaseOrder(
            po_number=number, order_date=date(2026, 8, 5),
            expected_date=date(2026, 8, 20),
            vendor_id=vendor.id, vendor_name='ACME Trading',
            vendor_tin='123-456-789-000', vendor_address='12 Rizal St, Makati',
            payment_terms='Net 30', reference='REF/2026 "urgent"',
            notes="Gate 2; ask for O'Brien.",
            vat_treatment='inclusive', status=status,
            subtotal=Decimal('25.50'), vat_amount=Decimal('2.73'),
            vat_override=True, total_amount=Decimal('25.50'),
            branch_id=branch.id)
        po.line_items.append(PurchaseOrderItem(
            line_number=1, product_id=product.id,
            description='Widget, 12" blade -- O\\'Brien spec',
            quantity=Decimal('2.5'), unit_price=Decimal('10.20'),
            amount=Decimal('25.50'), uom_text='pc', unit_of_measure_id=uom.id,
            vat_category='V12DG', vat_rate=Decimal('12.00'),
            line_total=Decimal('25.50'), vat_amount=Decimal('2.73')))
        if status != 'draft':
            po.approved_by_id = user.id
            po.approved_at = APPROVED_AT
        db.session.add(po)
        db.session.commit()
        return po

    live = make_po('PO-LIVE-0001', 'approved')
    write_revision(live, user.id)
    db.session.commit()

    make_po('PO-BACKFILL-0001', 'approved')
    make_po('PO-DRAFT-0001', 'draft')
'''


def _env(db_path):
    """flask_app.py's load_dotenv() does NOT override an already-set variable, so
    these win over .env -- and SECRET_KEY is supplied here rather than read from
    .env so the fixture works in a worktree that has no .env at all."""
    return {**os.environ,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'FLASK_APP': 'flask_app.py',
            'FLASK_ENV': 'development',
            'SECRET_KEY': 'test-secret-key-for-backfill-tests-only'}


def _run(args, db_path):
    result = subprocess.run(args, cwd=CAS_ROOT, env=_env(db_path),
                            capture_output=True, text=True)
    # pytest.fail, never pytest.skip: an unrunnable migration is a FAILURE.
    if result.returncode != 0:
        pytest.fail(f'{" ".join(str(a) for a in args)} exited {result.returncode}\n'
                    f'--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}')
    return result


def _build_db(directory):
    db_path = directory / 'po-rev0-backfill.db'
    db_path.touch()  # a 0-byte file is a valid empty SQLite database

    # The REAL schema at the pre-backfill revision. A conftest create_all() would
    # build today's model, not the migration history, and so cannot prove a
    # migration works.
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'docrev_0001'], db_path)

    seed = directory / 'seed_po_rev0.py'
    seed.write_text(_SEED_SCRIPT, encoding='utf-8')
    _run([sys.executable, str(seed), str(CAS_ROOT)], db_path)

    _run([sys.executable, '-m', 'flask', 'db', 'upgrade'], db_path)
    return db_path


@pytest.fixture(scope='module')
def migrated_db(tmp_path_factory):
    """One built-from-scratch, migrated database shared by the read-only tests.

    Module-scoped only because building it costs three subprocesses. Every test
    that consumes it reads; the downgrade test works on a copy.
    """
    return _build_db(tmp_path_factory.mktemp('po_rev0_backfill'))


def _revisions(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT p.po_number, r.revision_number, r.reason, r.snapshot_json "
            "FROM document_revisions r "
            "JOIN purchase_orders p ON p.id = r.document_id "
            "WHERE r.document_type = 'purchase_orders' "
            "ORDER BY p.po_number, r.revision_number").fetchall()
    finally:
        con.close()


def _by_po(db_path):
    out = {}
    for po_number, number, reason, snapshot in _revisions(db_path):
        out.setdefault(po_number, []).append((number, reason, json.loads(snapshot)))
    return out


def test_backfilled_rev0_equals_a_live_written_rev0(migrated_db):
    """The whole point of the migration: a reconstructed Rev 0 must be what
    write_revision() would have written for the same PO, key for key and value
    for value. Anything less and slice 2's validator compares a live Rev N
    against a baseline that was never in the same dialect."""
    revs = _by_po(migrated_db)
    assert set(revs) == {'PO-LIVE-0001', 'PO-BACKFILL-0001'}

    (live_number, live_reason, live), = revs['PO-LIVE-0001']
    (back_number, back_reason, back), = revs['PO-BACKFILL-0001']
    assert (live_number, back_number) == (0, 0)
    assert live_reason is None, 'a live capture is a baseline, not an amendment'
    assert 'reconstructed' in back_reason.lower(), \
        'a backfilled Rev 0 must not claim to be an original capture'

    # The parity assertion is only meaningful if the derived/formatted keys
    # actually carry values -- pin the ones the mutation testing targeted.
    assert live['header']['branch_name'] == 'Manila Branch'
    assert live['header']['vat_override'] == 'True'
    assert live['header']['approved_at'] == '2026-08-09T12:00:00'
    assert live['header']['total_amount_display'] == '25.50'
    assert live['lines'][0]['product_code'] == 'P-001'
    assert live['lines'][0]['uom_code'] == 'PCS'
    assert live['lines'][0]['unit_price_display'] == '10.20'

    # po_number and line_id are the ONLY values that legitimately differ between
    # two field-identical POs. Everything else, including vat_override and the
    # datetimes, must match exactly.
    assert live['header'].pop('po_number') == 'PO-LIVE-0001'
    assert back['header'].pop('po_number') == 'PO-BACKFILL-0001'
    assert len(live['lines']) == len(back['lines']) == 1
    for snapshot in (live, back):
        for line in snapshot['lines']:
            assert isinstance(line.pop('line_id'), int), 'line identity must stay a raw int'

    # Key sets first: a missing key fails here with a readable diff rather than
    # inside a 40-key value comparison.
    assert set(back['header']) == set(live['header'])
    assert [sorted(line) for line in back['lines']] == [sorted(line) for line in live['lines']]
    assert back == live


def test_only_non_draft_purchase_orders_are_backfilled(migrated_db):
    """Rev 0 means 'as approved'. A draft PO has never been approved, so it gets
    none -- but the non-draft control must be backfilled in the same run, or this
    test would pass with upgrade() replaced by `pass`."""
    revs = _by_po(migrated_db)

    assert 'PO-DRAFT-0001' not in revs, 'a draft PO must not be given a Rev 0'

    (number, reason, snapshot), = revs['PO-BACKFILL-0001']
    assert number == 0
    assert 'reconstructed' in reason.lower()
    assert snapshot['header']['status'] == 'approved'
    assert snapshot['lines'], 'lines must be captured, not just the header'


def test_a_live_captured_rev0_is_not_duplicated(migrated_db):
    """PO-LIVE-0001 already had a Rev 0 from the live approve path before the
    migration ran. Without the duplicate guard the INSERT violates
    uq_document_revision_number and the whole upgrade aborts -- so `migrated_db`
    existing at all is half the assertion (its `flask db upgrade` had to exit 0);
    the other half is that the surviving row is still the ORIGINAL capture."""
    rows = [r for r in _revisions(migrated_db) if r[0] == 'PO-LIVE-0001']
    assert len(rows) == 1, 'exactly one Rev 0 -- the migration must not add a second'
    po_number, number, reason, _ = rows[0]
    assert number == 0
    assert reason is None, 'the live capture must survive unmodified, not be overwritten'


def test_downgrade_removes_reconstructed_rows_and_spares_live_ones(tmp_path, migrated_db):
    """downgrade() is scoped by `reason`, so it must take back exactly what
    upgrade() added and leave a live-captured Rev 0 (reason IS NULL) in place."""
    dst = tmp_path / 'po-rev0-downgrade.db'
    shutil.copy(migrated_db, dst)

    _run([sys.executable, '-m', 'flask', 'db', 'downgrade', 'docrev_0001'], dst)

    remaining = [(po_number, number, reason)
                 for po_number, number, reason, _ in _revisions(dst)]
    assert remaining == [('PO-LIVE-0001', 0, None)]
