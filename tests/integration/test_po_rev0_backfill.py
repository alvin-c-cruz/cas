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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

CAS_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.slow, pytest.mark.purchase_orders]

# Seeded through the ORM so the live write_revision()/build_snapshot() path -- not
# a hand-rolled restatement of it -- produces the reference snapshot.
#
#  PO-LIVE-0001     approved + write_revision() -> a real Rev 0, reason NULL.
#                   The migration must LEAVE IT ALONE (duplicate-Rev-0 guard).
#  PO-BACKFILL-0001 field-identical to PO-LIVE-0001 apart from po_number, approved
#                   but with no revision -- the row the migration must reconstruct.
#  PO-DRAFT-0001    identical again but still draft -- must get nothing.
#  PO-CANCELLED-APPROVED-0001       approved_at set, then cancelled -- MUST be
#                   backfilled (it really was approved; status != 'draft' would
#                   also catch this one, so it doesn't discriminate the two
#                   predicates on its own -- it proves cancellation-after-
#                   approval doesn't suppress the backfill).
#  PO-CANCELLED-NEVER-APPROVED-0001 cancelled directly from draft (cancel()
#                   blocks only status in ('cancelled', 'closed'), never
#                   requires prior approval) -- approved_at/approved_by_id are
#                   NULL, so it must NOT be backfilled. This is the PO that
#                   `status != 'draft'` gets wrong: it is non-draft
#                   (status='cancelled') but was never approved.
#  PO-WIDE-LIVE-0001 / PO-WIDE-0001  the same live/backfill pair, but with line
#                   values carrying MORE decimal digits than their columns hold
#                   (quantity 0.12345 into Numeric(15,4), unit_price 10.005 and
#                   amount 1.2351 into Numeric(15,2)). The app accepts these --
#                   _dec() in purchase_orders/views.py never quantizes -- and
#                   SQLite stores the full float, so only the ORM's read-side
#                   rounding makes the live snapshot say '0.1235'. Every value in
#                   the round pair above already matches its column's scale, so
#                   the pair alone could not tell a scale-corrected backfill from
#                   an unscaled one.
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

    # The schema here is pinned at docrev_0001, but these rows are seeded through
    # TODAY'S ORM -- so every column added to a seeded table by a LATER migration
    # is in the INSERT and missing from the table, and the seed dies with
    # "table X has no column named Y". That is a property of the fixture, not of
    # the change that trips it (source_pr_item_id, pralloc_0001, was simply the
    # first). Reconcile automatically rather than hand-listing, so the next
    # column costs nothing. Only the seeded tables need it, and only ADD COLUMN
    # is possible on SQLite -- which is all a newer model can require.
    for model in (PurchaseOrder, PurchaseOrderItem):
        table = model.__table__
        have = {r[1] for r in db.session.execute(
            db.text('PRAGMA table_info(%s)' % table.name))}
        for col in table.columns:
            if col.name not in have:
                db.session.execute(db.text(
                    'ALTER TABLE %s ADD COLUMN %s %s'
                    % (table.name, col.name, col.type.compile(db.engine.dialect))))
    db.session.commit()

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

    # More digits than the columns hold: the ORM rounds these on read, so a
    # backfill that does not must produce a different snapshot.
    WIDE_LINE = dict(quantity=Decimal('0.12345'), unit_price=Decimal('10.005'),
                     amount=Decimal('1.2351'), line_total=Decimal('1.2351'))

    def make_po(number, status, line_overrides=None, approved=None):
        # `approved` defaults to "status is non-draft" (the old, WRONG
        # predicate) so most callers don't have to think about it -- but the
        # two cancellation fixtures below pass it explicitly, because for them
        # approval and terminal status must be independent of each other.
        if approved is None:
            approved = (status != 'draft')
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
        line = dict(
            line_number=1, product_id=product.id,
            description='Widget, 12" blade -- O\\'Brien spec',
            quantity=Decimal('2.5'), unit_price=Decimal('10.20'),
            amount=Decimal('25.50'), uom_text='pc', unit_of_measure_id=uom.id,
            vat_category='V12DG', vat_rate=Decimal('12.00'),
            line_total=Decimal('25.50'), vat_amount=Decimal('2.73'))
        line.update(line_overrides or {})
        po.line_items.append(PurchaseOrderItem(**line))
        if approved:
            po.approved_by_id = user.id
            po.approved_at = APPROVED_AT
        db.session.add(po)
        db.session.commit()
        return po

    live = make_po('PO-LIVE-0001', 'approved')
    # baseline=True is what approve() passes -- Rev 0 is the baseline SLOT, and
    # only a baseline write may claim it (an amendment of a document with no
    # baseline now starts at Rev 1). This seeds the live Rev 0 the migration must
    # leave alone, so it must be the same call approve() makes.
    write_revision(live, user.id, baseline=True)
    db.session.commit()

    make_po('PO-BACKFILL-0001', 'approved')
    make_po('PO-DRAFT-0001', 'draft')

    # approved, THEN cancelled -- cancel() never clears approved_at/
    # approved_by_id, so this PO really was approved and must still be
    # backfilled even though its current status is 'cancelled'.
    make_po('PO-CANCELLED-APPROVED-0001', 'cancelled', approved=True)

    # cancelled WITHOUT ever being approved -- cancel() blocks only
    # status in ('cancelled', 'closed'), so a draft PO can be cancelled
    # directly. approved_at/approved_by_id are NULL; `status != 'draft'`
    # would wrongly hand this one a Rev 0 captioned "as approved".
    make_po('PO-CANCELLED-NEVER-APPROVED-0001', 'cancelled', approved=False)

    # commit() above expired `wide_live`, so write_revision() re-reads its line
    # through the ORM -- i.e. through the Numeric rounding the migration has to
    # reproduce. Snapshotting the in-memory Decimals instead would compare the
    # backfill against values no live capture ever sees.
    wide_live = make_po('PO-WIDE-LIVE-0001', 'approved', WIDE_LINE)
    write_revision(wide_live, user.id, baseline=True)
    db.session.commit()

    make_po('PO-WIDE-0001', 'approved', WIDE_LINE)
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


def _assert_targets_tmp(env, tmp_root):
    """Refuse to launch a subprocess that could migrate a REAL database.

    These are the only tests in the suite that shell out to `flask db upgrade`,
    and their targeting rests entirely on _env() winning over .env via
    load_dotenv's non-override semantics. `.env` points at sqlite:///ric.db --
    a live client's working copy. One typo in _env, one subprocess that reloads
    dotenv with override=True, and an upgrade runs against real client data.
    So the target is proven to live under this test's tmp directory BEFORE the
    subprocess starts, not assumed."""
    uri = env.get('SQLALCHEMY_DATABASE_URI')
    prefix = 'sqlite:///'
    if not uri or not uri.startswith(prefix):
        pytest.fail(f'refusing to run: SQLALCHEMY_DATABASE_URI is {uri!r}, '
                    f'not a {prefix} path under the test tmp directory')
    target = Path(uri[len(prefix):]).resolve()
    root = Path(tmp_root).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        pytest.fail(f'refusing to run a migration against {target} -- it is outside '
                    f'the test tmp directory {root}. These subprocesses must never '
                    f'touch a real database (.env points at a live client DB).')


def _run(args, db_path, tmp_root):
    env = _env(db_path)
    _assert_targets_tmp(env, tmp_root)
    result = subprocess.run(args, cwd=CAS_ROOT, env=env,
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
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'docrev_0001'],
         db_path, directory)

    seed = directory / 'seed_po_rev0.py'
    seed.write_text(_SEED_SCRIPT, encoding='utf-8')
    _run([sys.executable, str(seed), str(CAS_ROOT)], db_path, directory)

    # docrev_0002 explicitly, not `upgrade` to head: this fixture exists to
    # exercise docrev_0002's backfill, and running every LATER migration too
    # couples the test to unrelated schema work -- pralloc_0001 would try to add
    # source_pr_item_id, which the shim above has already added, and fail on a
    # duplicate column. The module docstring always said docrev_0002; head only
    # happened to equal it when this was written.
    _run([sys.executable, '-m', 'flask', 'db', 'upgrade', 'docrev_0002'],
         db_path, directory)
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


def _comparable_pair(revs, live_po, back_po):
    """The live and the backfilled Rev 0 of a field-identical pair of POs, with
    the only two values that may legitimately differ -- po_number and line_id --
    asserted and then removed, so the caller can compare everything else."""
    (live_number, live_reason, live), = revs[live_po]
    (back_number, back_reason, back), = revs[back_po]
    assert (live_number, back_number) == (0, 0)
    assert live_reason is None, 'a live capture is a baseline, not an amendment'
    assert 'reconstructed' in back_reason.lower(), \
        'a backfilled Rev 0 must not claim to be an original capture'

    assert live['header'].pop('po_number') == live_po
    assert back['header'].pop('po_number') == back_po
    assert len(live['lines']) == len(back['lines']) == 1
    for snapshot in (live, back):
        for line in snapshot['lines']:
            assert isinstance(line.pop('line_id'), int), 'line identity must stay a raw int'
    return live, back


def _assert_identical(live, back):
    # Key sets first: a missing key fails here with a readable diff rather than
    # inside a 40-key value comparison.
    assert set(back['header']) == set(live['header'])
    assert [sorted(line) for line in back['lines']] == [sorted(line) for line in live['lines']]
    assert back == live


def test_the_subprocess_guard_refuses_a_database_outside_tmp(tmp_path):
    """The guard is the only thing standing between a typo in _env() and
    `flask db upgrade` running against the sqlite:///ric.db in .env, so prove it
    is LIVE -- an unexercised guard fails open and nothing ever notices."""
    for uri in ('sqlite:///ric.db', f'sqlite:///{CAS_ROOT / "instance" / "ric.db"}', None):
        with pytest.raises(pytest.fail.Exception) as exc:
            _assert_targets_tmp({'SQLALCHEMY_DATABASE_URI': uri}, tmp_path)
        assert 'refusing to run' in str(exc.value)

    # ...and does NOT refuse the real thing, or it would just be a broken test.
    _assert_targets_tmp(_env(tmp_path / 'ok.db'), tmp_path)


def test_backfilled_rev0_equals_a_live_written_rev0(migrated_db):
    """The whole point of the migration: a reconstructed Rev 0 must be what
    write_revision() would have written for the same PO, key for key and value
    for value. Anything less and slice 2's validator compares a live Rev N
    against a baseline that was never in the same dialect."""
    revs = _by_po(migrated_db)
    assert set(revs) == {'PO-LIVE-0001', 'PO-BACKFILL-0001',
                         'PO-WIDE-LIVE-0001', 'PO-WIDE-0001',
                         'PO-CANCELLED-APPROVED-0001'}

    live, back = _comparable_pair(revs, 'PO-LIVE-0001', 'PO-BACKFILL-0001')

    # The parity assertion is only meaningful if the derived/formatted keys
    # actually carry values -- pin the ones the mutation testing targeted.
    assert live['header']['branch_name'] == 'Manila Branch'
    assert live['header']['vat_override'] == 'True'
    assert live['header']['approved_at'] == '2026-08-09T12:00:00'
    assert live['header']['total_amount_display'] == '25.50'
    assert live['lines'][0]['product_code'] == 'P-001'
    assert live['lines'][0]['uom_code'] == 'PCS'
    assert live['lines'][0]['unit_price_display'] == '10.20'

    # Everything else, including vat_override and the datetimes, must match.
    _assert_identical(live, back)


def test_out_of_scale_numerics_are_rounded_the_way_the_orm_rounds_them(migrated_db):
    """SQLite stores a Numeric as a plain float, and SQLAlchemy's read processor
    rebuilds it as Decimal('%.<scale>f' % raw) -- so the live canonical() only
    ever sees values already rounded to the column's scale, while the migration
    reads the raw float. `Decimal(str(raw))` therefore keeps digits the ORM drops
    and the two Rev 0s diverge on exactly the POs a user can create today
    (_dec() in purchase_orders/views.py never quantizes).

    The round-number pair above cannot see this: every one of its values already
    matches its column's scale, so it passes with the scaling removed."""
    revs = _by_po(migrated_db)
    live, back = _comparable_pair(revs, 'PO-WIDE-LIVE-0001', 'PO-WIDE-0001')

    # The LIVE capture is the specification -- pinned so a drift in either
    # implementation, not just a divergence between them, is visible.
    line = live['lines'][0]
    assert line['quantity'] == '0.1235', 'Numeric(15, 4) -- 0.12345 rounds on read'
    assert line['unit_price'] == '10.01', 'Numeric(15, 2) -- 10.005 rounds on read'
    assert line['amount'] == '1.24'
    assert line['line_total'] == '1.24'
    # The display forms round from the ORM's already-rounded Decimal, not from
    # the raw float -- quantizing 10.005 directly would give '10.00'.
    assert line['unit_price_display'] == '10.01'
    assert line['amount_display'] == '1.24'

    _assert_identical(live, back)


def test_backfilled_rows_are_stamped_in_philippine_time(migrated_db):
    """amended_at is written from a hand-rolled PHT constant (a migration cannot
    import app.utils.ph_now). Nothing else in this file reads it beyond a NOT
    NULL column, so flipping that constant's sign -- an 8-hour skew that shows
    the PREVIOUS day's date on any upgrade after 16:00 PH, the exact bug the
    constant exists to prevent -- left every other test in this file green."""
    con = sqlite3.connect(migrated_db)
    try:
        stamps = [row[0] for row in con.execute(
            "SELECT amended_at FROM document_revisions "
            "WHERE document_type = 'purchase_orders' AND reason IS NOT NULL").fetchall()]
    finally:
        con.close()
    assert stamps, 'no backfilled rows to check'

    ph_now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    for stamp in stamps:
        written = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S.%f')
        drift = abs((ph_now - written).total_seconds())
        assert drift < 600, (
            f'amended_at is {stamp}, {drift / 3600:.1f}h from PH now ({ph_now}) '
            f'-- the migration is not stamping Philippine time')


def test_backfill_selects_by_approved_at_not_by_status(migrated_db):
    """Rev 0 means 'as approved at some point', so the selection predicate is
    `approved_at IS NOT NULL`, not `status != 'draft'`. The two predicates only
    disagree on a PO that is non-draft but was never approved -- a draft PO
    cancelled directly (cancel() blocks only status in ('cancelled',
    'closed'), never requires prior approval). Four outcomes, by PO number:

    - PO-DRAFT-0001: never approved, still draft -> no Rev 0 (both predicates
      agree).
    - PO-BACKFILL-0001: approved, still 'approved' -> Rev 0 (both predicates
      agree; a plain positive control).
    - PO-CANCELLED-APPROVED-0001: approved_at set, then cancelled -> Rev 0.
      `status != 'draft'` also backfills this one, so it alone would not
      catch a regression back to the old predicate -- it exists to prove
      cancellation-after-approval does not suppress a backfill it deserves.
    - PO-CANCELLED-NEVER-APPROVED-0001: never approved, cancelled directly
      from draft -> NO Rev 0. This is the discriminating case: `status !=
      'draft'` would give it a Rev 0 captioned "as approved" that it never
      was -- exactly the affirmative false claim this feature exists to
      remove. `approved_at IS NOT NULL` correctly excludes it.
    """
    revs = _by_po(migrated_db)

    assert 'PO-DRAFT-0001' not in revs, 'a draft PO must not be given a Rev 0'
    assert 'PO-CANCELLED-NEVER-APPROVED-0001' not in revs, (
        'a PO cancelled without ever being approved must not get a Rev 0 '
        'captioned "as approved" -- its approved_at is NULL')

    (number, reason, snapshot), = revs['PO-BACKFILL-0001']
    assert number == 0
    assert 'reconstructed' in reason.lower()
    assert snapshot['header']['status'] == 'approved'
    assert snapshot['lines'], 'lines must be captured, not just the header'

    (number, reason, snapshot), = revs['PO-CANCELLED-APPROVED-0001']
    assert number == 0
    assert 'reconstructed' in reason.lower()
    assert snapshot['header']['status'] == 'cancelled', (
        'the snapshot reflects CURRENT state (reconstructed, not captured at '
        'approval time) -- this PO must still get a Rev 0 despite its '
        'current status being cancelled')
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

    _run([sys.executable, '-m', 'flask', 'db', 'downgrade', 'docrev_0001'], dst, tmp_path)

    remaining = [(po_number, number, reason)
                 for po_number, number, reason, _ in _revisions(dst)]
    assert remaining == [('PO-LIVE-0001', 0, None), ('PO-WIDE-LIVE-0001', 0, None)]
