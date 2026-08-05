"""backfill Rev 0 for pre-existing confirmed Sales Orders

Revision ID: sorev_0002
Revises: sorev_0001
Create Date: 2026-08-04

Existing confirmed SOs predate revision tracking, so their Rev 0 is
RECONSTRUCTED FROM CURRENT STATE, not captured at confirm time. For any SO that
was edited while still draft, this snapshot is not literally what was confirmed
-- so every backfilled row says so in its `reason`, and the UI shows it.
Claiming otherwise would be exactly the dishonesty this feature exists to remove.

The snapshot below MUST emit the same key set app/sales_orders/revisions.py's
build_snapshot() emits, because revision_view.html renders it. An earlier
version of this migration wrote only so_number/status; the viewer reads 19
header keys, so all 121 real RIC orders rendered a document that was not
merely blank but FALSE -- `{{ header.salesperson_name or 'Company Account' }}`
turned a missing key into an affirmative claim, and every price/total fell
through to an em-dash that reads as "the original order had no prices". A
migration cannot `import app.` (no app/DB context here), so `_s`/`_money`
below are standalone reimplementations of revisions.py's canonical/display
formatting, applied per-field (raw sqlite3 rows are plain Python primitives --
int/float/str/None -- not the ORM-typed Decimal/date/bool objects
revisions.py's polymorphic `_s` dispatches on).
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from alembic import op
import sqlalchemy as sa

revision = 'sorev_0002'
down_revision = 'sorev_0001'
branch_labels = None
depends_on = None

RECONSTRUCTED = 'Rev 0 - reconstructed at upgrade, not an original capture'

# Philippine Standard Time (UTC+8) -- mirrors app.utils_helpers.ph_now without
# importing app code. Everything else this feature writes (write_revision's
# amended_at, confirmed_at, created_at, ...) is stamped in PH time; CURRENT_TIMESTAMP
# is SQLite's UTC clock, an 8-hour skew that shows the previous day's date on any
# upgrade run after 16:00 PH.
_PHT = timezone(timedelta(hours=8))


def _ph_timestamp():
    """Naive 'YYYY-MM-DD HH:MM:SS.ffffff' string, matching how a ph_now()-defaulted
    DateTime column is actually stored on disk (no timezone-offset suffix)."""
    return datetime.now(_PHT).strftime('%Y-%m-%d %H:%M:%S.%f')


def _s(value):
    """Canonical Decimal string for a raw NUMERIC column value (int/float from
    sqlite3), mirroring revisions.py's _s Decimal branch: normalised, no
    scientific notation, -0 collapsed to 0. Only for Numeric columns -- ids,
    dates, bools and plain text are converted separately below."""
    if value is None:
        return None
    d = Decimal(str(value))
    if d == 0:
        d = abs(d)
    return format(d.normalize(), 'f')


def _money(value):
    """2-dp display string, mirroring revisions.py's _money."""
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')


def _int_s(value):
    """FK ids and line_number all go through revisions.py's polymorphic _s too,
    but since a plain int is neither Decimal nor date-like there, it falls
    through to str(value). Reproduce that exact output."""
    return str(value) if value is not None else None


def _iso_dt(value):
    """DateTime columns come back from sqlite3 as 'YYYY-MM-DD HH:MM:SS.ffffff'
    (space-separated); revisions.py's _s calls a live datetime object's
    .isoformat(), which uses 'T'. Swap the separator so a backfilled Rev 0 and
    a live-captured Rev N serialise confirmed_at/cancelled_at/closed_at
    identically."""
    return value.replace(' ', 'T') if value is not None else None


def upgrade():
    conn = op.get_bind()
    ts = _ph_timestamp()

    orders = conn.execute(sa.text(
        "SELECT so.id, so.branch_id, so.so_number, so.order_date, "
        "       so.expected_delivery_date, so.customer_id, so.customer_name, "
        "       so.customer_tin, so.customer_address, so.customer_po_number, "
        "       so.customer_po_date, so.payment_terms, so.reference, so.notes, "
        "       so.salesperson_id, so.subtotal, so.vat_amount, so.vat_override, "
        "       so.total_amount, so.status, so.confirmed_by_id, so.confirmed_at, "
        "       so.cancelled_by_id, so.cancelled_at, so.cancel_reason, "
        "       e.first_name, e.middle_name, e.last_name "
        "FROM sales_orders so "
        "LEFT JOIN employees e ON e.id = so.salesperson_id "
        "WHERE so.status = 'confirmed'")).fetchall()

    for (so_id, branch_id, so_number, order_date, expected_delivery_date,
         customer_id, customer_name, customer_tin, customer_address,
         customer_po_number, customer_po_date, payment_terms, reference, notes,
         salesperson_id, subtotal, vat_amount, vat_override, total_amount, status,
         confirmed_by_id, confirmed_at, cancelled_by_id, cancelled_at, cancel_reason,
         sp_first, sp_middle, sp_last) in orders:

        # Must mirror downgrade()'s predicate. downgrade() deletes only
        # revision_number = 0 rows carrying RECONSTRUCTED, so skipping on ANY
        # revision existing means: downgrade then re-upgrade leaves an order
        # that had a Rev 1 permanently WITHOUT its Rev 0 -- /revisions/0 404s
        # and the print banner cites a "Supersedes Rev. 0" that does not exist.
        exists = conn.execute(sa.text(
            "SELECT 1 FROM sales_order_revisions "
            "WHERE sales_order_id = :sid AND revision_number = 0"),
            {'sid': so_id}).first()
        if exists:
            continue

        salesperson_name = None
        if salesperson_id is not None:
            parts = [p for p in (sp_first, sp_middle, sp_last) if p]
            salesperson_name = ' '.join(parts) or None

        header = {
            'so_number': so_number, 'order_date': order_date,
            'expected_delivery_date': expected_delivery_date,
            'customer_id': _int_s(customer_id), 'customer_name': customer_name,
            'customer_tin': customer_tin, 'customer_address': customer_address,
            'customer_po_number': customer_po_number,
            'customer_po_date': customer_po_date,
            'payment_terms': payment_terms, 'reference': reference, 'notes': notes,
            'salesperson_id': _int_s(salesperson_id),
            'subtotal': _s(subtotal), 'vat_amount': _s(vat_amount),
            'vat_override': str(bool(vat_override)), 'total_amount': _s(total_amount),
            'status': status,
            'confirmed_by_id': _int_s(confirmed_by_id), 'confirmed_at': _iso_dt(confirmed_at),
            'cancelled_by_id': _int_s(cancelled_by_id), 'cancelled_at': _iso_dt(cancelled_at),
            'cancel_reason': cancel_reason,
            'salesperson_name': salesperson_name,
            'subtotal_display': _money(subtotal), 'vat_amount_display': _money(vat_amount),
            'total_amount_display': _money(total_amount),
        }

        lines = conn.execute(sa.text(
            "SELECT i.id, i.line_number, i.product_id, i.quantity, "
            "       i.unit_of_measure_id, i.uom_text, i.unit_price, i.amount, "
            "       i.vat_amount, i.vat_category, i.vat_rate, i.wt_id, "
            "       i.line_status, i.closed_by_id, i.closed_at, i.closed_reason, "
            "       i.line_total, i.delivery_date, i.delivery_site_id, "
            "       p.code, p.name, ds.name, wt.code, uom.code "
            "FROM sales_order_items i "
            "LEFT JOIN products p ON p.id = i.product_id "
            "LEFT JOIN customer_delivery_sites ds ON ds.id = i.delivery_site_id "
            "LEFT JOIN withholding_tax wt ON wt.id = i.wt_id "
            "LEFT JOIN units_of_measure uom ON uom.id = i.unit_of_measure_id "
            "WHERE i.sales_order_id = :sid ORDER BY i.line_number"),
            {'sid': so_id}).fetchall()

        line_rows = []
        for (line_id, line_number, product_id, quantity, unit_of_measure_id,
             uom_text, unit_price, amount, line_vat_amount, vat_category, vat_rate,
             wt_id, line_status, closed_by_id, closed_at, closed_reason, line_total,
             delivery_date, delivery_site_id, product_code, product_name,
             delivery_site_name, wt_code, uom_code) in lines:

            uom_display = uom_code if unit_of_measure_id is not None else uom_text

            line_rows.append({
                'line_number': _int_s(line_number), 'product_id': _int_s(product_id),
                'quantity': _s(quantity),
                'unit_of_measure_id': _int_s(unit_of_measure_id), 'uom_text': uom_text,
                'unit_price': _s(unit_price), 'amount': _s(amount),
                'vat_amount': _s(line_vat_amount), 'vat_category': vat_category,
                'vat_rate': _s(vat_rate), 'wt_id': _int_s(wt_id),
                'line_status': line_status, 'closed_by_id': _int_s(closed_by_id),
                'closed_at': _iso_dt(closed_at), 'closed_reason': closed_reason,
                'line_total': _s(line_total), 'delivery_date': delivery_date,
                'delivery_site_id': _int_s(delivery_site_id),
                # Identity -- a raw int, not string-converted, matching
                # revisions.py's build_snapshot (`row['line_id'] = item.id`).
                'line_id': line_id,
                'product_code': product_code, 'product_name': product_name,
                'delivery_site_name': delivery_site_name, 'wt_code': wt_code,
                'uom_display': uom_display,
                'unit_price_display': _money(unit_price),
                'amount_display': _money(amount),
            })

        snapshot = {'header': header, 'lines': line_rows}

        conn.execute(sa.text(
            "INSERT INTO sales_order_revisions "
            "(sales_order_id, revision_number, snapshot_json, reason, "
            " amended_at, branch_id) "
            "VALUES (:sid, 0, :snap, :reason, :ts, :bid)"),
            {'sid': so_id, 'snap': json.dumps(snapshot),
             'reason': RECONSTRUCTED, 'ts': ts, 'bid': branch_id})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM sales_order_revisions WHERE revision_number = 0 "
        "AND reason = :reason"), {'reason': RECONSTRUCTED})
