"""backfill Rev 0 for pre-existing non-draft Purchase Orders

Revision ID: docrev_0002
Revises: docrev_0001
Create Date: 2026-08-09

POs approved before revision tracking have no Rev 0, so theirs is RECONSTRUCTED
FROM CURRENT STATE rather than captured at approval. Any PO edited while still
draft has a snapshot that is not literally what was approved -- so every
backfilled row says so in its `reason`, and the UI shows it. Claiming otherwise
would be exactly the dishonesty this feature exists to remove.

The snapshot below MUST emit the same key set PurchaseOrder.build_snapshot()
emits, because the revision viewer renders it. When the Sales Order equivalent
wrote only two keys, the viewer's other 17 fell through to defaults and rendered
a document that was not blank but FALSE.

A migration cannot `import app.`, so the formatters below are standalone
reimplementations applied PER FIELD -- raw sqlite3 rows are plain primitives
(int/float/str/None), not the ORM-typed objects the app's canonical() dispatches
on. Two of those primitives need field-specific correction, not just plain
str(value), confirmed against a live copy of philgen.db before writing this:

  - vat_override is Boolean. sqlite3 hands back the on-disk int (0/1), but
    canonical(True/False) is str(bool) -> 'True'/'False'. str(1) would give
    '1', silently mismatching a live-captured revision's text forever.
  - approved_at/cancelled_at are DateTime. sqlite3 hands back the on-disk TEXT
    with a SPACE separator ('2026-08-09 16:21:38.879856'), but
    canonical(datetime_obj) is value.isoformat() (a 'T' separator). Confirmed
    live: order_date/expected_date are plain Date columns and already match
    date.isoformat() with no conversion needed -- only the two DateTime
    columns need the separator swap. Mirrors sorev_0002's `_iso_dt` fix.

Both are load-bearing because canonical()'s whole job is EQUALITY: two
snapshots of an unchanged document must compare textually equal. A backfilled
Rev 0 that doesn't match what a live write_revision() would have produced for
the same values breaks that contract for slice 2's validator.
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision = 'docrev_0002'
down_revision = 'docrev_0001'
branch_labels = None
depends_on = None

RECONSTRUCTED = 'Rev 0 - reconstructed at upgrade, not an original capture'

# Philippine Standard Time (UTC+8), mirroring app.utils.ph_now without importing
# app code. CURRENT_TIMESTAMP is SQLite's UTC clock -- an 8-hour skew that shows
# the previous day's date on any upgrade run after 16:00 PH.
_PHT = timezone(timedelta(hours=8))

HEADER_FIELDS = (
    'po_number', 'order_date', 'expected_date', 'vendor_id', 'vendor_name',
    'vendor_tin', 'vendor_address', 'payment_terms', 'reference', 'notes',
    'vat_treatment', 'status', 'subtotal', 'vat_amount', 'vat_override',
    'total_amount', 'purchase_request_id', 'accounts_payable_id', 'branch_id',
    'approved_by_id', 'approved_at', 'cancelled_by_id', 'cancelled_at', 'cancel_reason',
)
MONEY_FIELDS = ('subtotal', 'vat_amount', 'total_amount')
LINE_FIELDS = (
    'line_number', 'product_id', 'description', 'quantity', 'unit_price',
    'amount', 'uom_text', 'unit_of_measure_id', 'vat_category', 'vat_rate',
    'line_total', 'vat_amount',
)
NUMERIC_FIELDS = set(MONEY_FIELDS) | {
    'quantity', 'unit_price', 'amount', 'line_total', 'vat_rate', 'vat_amount'}
BOOL_FIELDS = {'vat_override'}
DATETIME_FIELDS = {'approved_at', 'cancelled_at'}


def _ph_timestamp():
    """Naive 'YYYY-MM-DD HH:MM:SS.ffffff', matching how a ph_now()-defaulted
    DateTime column is actually stored on disk (no timezone-offset suffix)."""
    return datetime.now(_PHT).strftime('%Y-%m-%d %H:%M:%S.%f')


def _canonical(name, value):
    """Canonical string for a raw column value, dispatched BY FIELD NAME --
    a raw sqlite3 row gives only int/float/str/None, so there is no type to
    sniff the way the app's canonical() does on live ORM objects."""
    if value is None:
        return None
    if name in NUMERIC_FIELDS:
        d = Decimal(str(value))
        if d == 0:
            d = abs(d)
        return format(d.normalize(), 'f')
    if name in BOOL_FIELDS:
        return str(bool(value))
    if name in DATETIME_FIELDS:
        return str(value).replace(' ', 'T')
    return str(value)


def _money(value):
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')


def upgrade():
    conn = op.get_bind()
    stamp = _ph_timestamp()

    pos = conn.exec_driver_sql(
        "SELECT id, %s FROM purchase_orders WHERE status != 'draft'"
        % ', '.join(HEADER_FIELDS)).fetchall()

    for po in pos:
        po_id = po[0]

        # Guard against a duplicate Rev 0: if this PO was approved through the
        # live write_revision() path (Task 5) before this migration ran, it
        # already has a Rev 0 -- inserting a second one would violate
        # uq_document_revision_number. Mirrors sorev_0002's identical guard,
        # which also protects a downgrade-then-re-upgrade cycle.
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM document_revisions WHERE document_type='purchase_orders' "
            "AND document_id=%d AND revision_number=0" % po_id).fetchone()
        if exists:
            continue

        header = {}
        for i, name in enumerate(HEADER_FIELDS, start=1):
            header[name] = _canonical(name, po[i])
        for name in MONEY_FIELDS:
            header[f'{name}_display'] = _money(po[HEADER_FIELDS.index(name) + 1])

        branch_id = po[HEADER_FIELDS.index('branch_id') + 1]
        branch_row = None
        if branch_id is not None:
            branch_row = conn.exec_driver_sql(
                "SELECT name FROM branches WHERE id = %d" % branch_id).fetchone()
        header['branch_name'] = branch_row[0] if branch_row else None

        line_rows = conn.exec_driver_sql(
            "SELECT id, %s, product_id FROM purchase_order_items "
            "WHERE purchase_order_id = %d ORDER BY line_number, id"
            % (', '.join(LINE_FIELDS), po_id)).fetchall()

        lines = []
        for row in line_rows:
            line = {'line_id': row[0]}
            for i, name in enumerate(LINE_FIELDS, start=1):
                line[name] = _canonical(name, row[i])
            product_id = row[len(LINE_FIELDS) + 1]
            product = None
            if product_id is not None:
                product = conn.exec_driver_sql(
                    "SELECT code, name FROM products WHERE id = %d" % product_id).fetchone()
            line['product_code'] = product[0] if product else None
            line['product_name'] = product[1] if product else None
            # Read the RAW row value, not line['unit_of_measure_id'] -- that one has
            # already been canonicalised to a string by the loop above.
            uom_id = row[LINE_FIELDS.index('unit_of_measure_id') + 1]
            uom = None
            if uom_id is not None:
                uom = conn.exec_driver_sql(
                    "SELECT code FROM units_of_measure WHERE id = %d" % int(uom_id)).fetchone()
            line['uom_code'] = uom[0] if uom else line.get('uom_text')
            line['unit_price_display'] = _money(row[LINE_FIELDS.index('unit_price') + 1])
            line['amount_display'] = _money(row[LINE_FIELDS.index('amount') + 1])
            lines.append(line)

        snapshot = json.dumps({'header': header, 'lines': lines})
        # Bound parameters, not string interpolation: snapshot_json is arbitrary
        # user text (vendor names, notes) and WILL contain quotes.
        conn.execute(
            sa.text(
                "INSERT INTO document_revisions "
                "(document_type, document_id, revision_number, snapshot_json, reason, "
                " authorizing_reference, amended_by_id, amended_at, branch_id) "
                "VALUES ('purchase_orders', :doc_id, 0, :snap, :reason, "
                "        NULL, NULL, :stamp, :branch_id)"),
            {'doc_id': po_id, 'snap': snapshot, 'reason': RECONSTRUCTED,
             'stamp': stamp, 'branch_id': branch_id})


def downgrade():
    op.get_bind().exec_driver_sql(
        "DELETE FROM document_revisions WHERE document_type = 'purchase_orders' "
        "AND revision_number = 0 AND reason = '%s'" % RECONSTRUCTED)
