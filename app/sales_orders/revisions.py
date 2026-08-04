"""Snapshot service for Sales Order revisions.

A revision records what the order WAS. Nothing here computes what CHANGED --
see the spec's "Why there is no computed change summary". The UI renders two
snapshots side by side rather than trusting a derived summary, because a wrong
summary printed on a factory-floor job order slip is worse than none.

build_snapshot is pure. write_revision touches the session but never commits --
the caller owns the transaction so a revision and the edit that produced it land
atomically.
"""
import json
from decimal import Decimal

from app import db
from app.sales_orders.revision_models import SalesOrderRevision

HEADER_FIELDS = (
    'so_number', 'order_date', 'expected_delivery_date', 'customer_id',
    'customer_name', 'customer_tin', 'customer_address', 'customer_po_number',
    'customer_po_date', 'payment_terms', 'reference', 'notes', 'salesperson_id',
    'subtotal', 'vat_amount', 'vat_override', 'total_amount', 'status',
    # Provenance: who confirmed this order as originally placed, when, and how cancellation
    # (if any) was recorded. Rev 0 is 'the order as originally confirmed' -- losing provenance
    # makes that snapshot incomplete.
    'confirmed_by_id', 'confirmed_at', 'cancelled_by_id', 'cancelled_at', 'cancel_reason',
)

LINE_FIELDS = (
    'line_number', 'product_id', 'quantity', 'unit_of_measure_id', 'uom_text',
    'unit_price', 'amount', 'vat_amount', 'vat_category', 'vat_rate', 'wt_id', 'line_status',
    'closed_by_id', 'closed_at', 'closed_reason', 'line_total', 'delivery_date', 'delivery_site_id',
)


def _s(value):
    """JSON-safe CANONICAL string form. Dates ISO; Decimals normalised.

    Normalising is load-bearing: the same value stringifies differently
    depending on origin. A Numeric(15,4) column read back from SQLite gives
    Decimal('3000.0000') -> '3000.0000', while the form parser gives
    Decimal('3000') -> '3000'. Two snapshots of an UNCHANGED order must compare
    equal, so both sides must canonicalise to the same text.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Decimal('-0') == Decimal('0') is True but they would render '-0' and
        # '0' -- equal values with unequal text is the exact failure this guards.
        if value == 0:
            value = abs(value)
        # format(..., 'f') avoids the scientific notation normalize() produces
        # for large integral values (Decimal('3000').normalize() is 3E+3).
        return format(value.normalize(), 'f')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _money(value):
    """DISPLAY form for money: always 2 decimal places.

    Deliberately separate from _s. _s canonicalises for EQUALITY, which collapses
    Decimal('4.20') to '4.2' -- correct for comparing snapshots, wrong on a
    printed slip where money must read as 4.20.
    """
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')


def build_snapshot(so):
    """Complete order state -- header + all lines -- as of right now.

    FK-backed values carry a resolved name alongside the id, and money carries a
    2-dp display string alongside the canonical one, because this snapshot is
    rendered to a person.
    """
    header = {k: _s(getattr(so, k)) for k in HEADER_FIELDS}
    header['salesperson_name'] = so.salesperson.full_name if so.salesperson else None
    header['subtotal_display'] = _money(so.subtotal)
    header['vat_amount_display'] = _money(so.vat_amount)
    header['total_amount_display'] = _money(so.total_amount)

    lines = []
    for item in sorted(so.line_items, key=lambda i: (i.line_number or 0, i.id or 0)):
        row = {f: _s(getattr(item, f)) for f in LINE_FIELDS}
        # Identity -- a raw int, not passed through _s, so lookups stay exact.
        row['line_id'] = item.id
        row['product_code'] = item.product.code if item.product else None
        row['product_name'] = item.product.name if item.product else None
        row['delivery_site_name'] = (item.delivery_site.name
                                     if item.delivery_site else None)
        row['wt_code'] = item.withholding_tax.code if item.withholding_tax else None
        row['uom_display'] = (item.unit_of_measure.code
                              if item.unit_of_measure else item.uom_text)
        row['unit_price_display'] = _money(item.unit_price)
        row['amount_display'] = _money(item.amount)
        lines.append(row)

    return {'header': header, 'lines': lines}


def latest_revision(so_id):
    return (SalesOrderRevision.query
            .filter_by(sales_order_id=so_id)
            .order_by(SalesOrderRevision.revision_number.desc())
            .first())


def write_revision(so, user_id, reason=None, authorizing_po=None):
    """Append the next revision for *so*. Adds to the session; does NOT commit."""
    # Flush first: a line appended but not yet flushed has id None, and the
    # snapshot's line identity depends on that id existing. Default autoflush
    # would usually cover this, which is exactly why it is explicit.
    db.session.flush()

    prev = latest_revision(so.id)
    rev = SalesOrderRevision(
        sales_order_id=so.id,
        revision_number=0 if prev is None else prev.revision_number + 1,
        snapshot_json=json.dumps(build_snapshot(so)),
        reason=reason,
        authorizing_po_number=authorizing_po,
        amended_by_id=user_id,
        branch_id=so.branch_id,
    )
    db.session.add(rev)
    return rev
