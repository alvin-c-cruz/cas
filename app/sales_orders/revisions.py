"""Snapshot + change-summary services for Sales Order revisions.

build_snapshot / summarize_change are pure: no request context, no session.
write_revision touches the session but never commits -- the caller owns the
transaction so a revision and the order edit that produced it land atomically.
"""
import json
from decimal import Decimal

from app import db
from app.sales_orders.revision_models import SalesOrderRevision

# Header fields captured in a snapshot and diffed for the change summary.
# Key -> human label used in the revision history panel.
HEADER_FIELDS = {
    'so_number': 'SO number',
    'order_date': 'Order date',
    'expected_delivery_date': 'Expected delivery date',
    'customer_id': 'Customer',
    'customer_name': 'Customer',
    'customer_po_number': 'Customer PO #',
    'customer_po_date': 'Customer PO date',
    'payment_terms': 'Payment terms',
    'reference': 'Reference',
    'notes': 'Notes',
    'salesperson_id': 'Salesperson',
    'subtotal': 'Subtotal',
    'vat_amount': 'VAT',
    'total_amount': 'Total',
    'status': 'Status',
}

# Fields whose change is noise in a history panel (they move as a consequence of
# a line edit, which is already reported) or are not user-meaningful.
_HEADER_FIELDS_NOT_SUMMARISED = {
    'customer_id', 'salesperson_id', 'subtotal', 'vat_amount', 'total_amount',
}

LINE_FIELDS = (
    'line_number', 'product_id', 'product_code', 'product_name', 'quantity',
    'unit_of_measure_id', 'uom_text', 'unit_price', 'amount', 'vat_category',
    'vat_rate', 'wt_id', 'line_status', 'delivery_date', 'delivery_site_id',
)


def _s(value):
    """JSON-safe, CANONICAL string form. Dates ISO; Decimals normalised.

    Normalising Decimals is not cosmetic -- it is load-bearing. The same value
    stringifies differently depending on where it came from: a Numeric(15,4)
    column read back from SQLite gives Decimal('3000.0000') -> '3000.0000',
    while the amend route's own parser gives Decimal('3000') -> '3000'. Snapshots
    are taken from the in-session object, so a diff would otherwise compare
    DB-shaped strings against form-shaped strings and report a change on every
    single line of an amendment that changed nothing at all.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        # normalize() collapses trailing zeros; format(..., 'f') avoids the
        # scientific notation normalize() produces for large integral values
        # (Decimal('3000').normalize() is Decimal('3E+3')).
        return format(value.normalize(), 'f')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def build_snapshot(so):
    """Complete order state -- header + all lines -- as of right now."""
    header = {k: _s(getattr(so, k, None)) for k in HEADER_FIELDS}
    lines = []
    for item in sorted(so.line_items, key=lambda i: (i.line_number or 0, i.id or 0)):
        row = {}
        for f in LINE_FIELDS:
            row[f] = _s(getattr(item, f, None))
        # The row's own identity -- the only stable handle across revisions.
        # Kept as an int, not passed through _s(), so lookups are exact.
        row['line_id'] = item.id
        row['product_code'] = item.product.code if item.product else None
        row['product_name'] = item.product.name if item.product else None
        # Resolve FKs to human-readable values -- the change summary is read by
        # people, and on a printed job order slip a bare integer is useless.
        row['delivery_site_name'] = (item.delivery_site.name
                                     if item.delivery_site else None)
        row['wt_code'] = (item.withholding_tax.code
                          if item.withholding_tax else None)
        row['uom_display'] = (item.unit_of_measure.code
                              if item.unit_of_measure else item.uom_text)
        lines.append(row)
    return {'header': header, 'lines': lines}


# Line fields whose change is user-meaningful and therefore summarised.
# (compare_field, label, display_field). The comparison is done on the FIRST
# element and the value shown to the reader comes from the THIRD -- so a change
# is detected on the stable id but rendered as a human-readable name. Two
# delivery sites can share a name (CustomerDeliverySite has no unique constraint
# on (customer_id, name)), so comparing names alone would hide a real change.
# `quantity` is handled specially (kind 'qty') so it renders as the headline
# change it usually is.
SUMMARISED_LINE_FIELDS = (
    ('quantity', 'Qty', 'quantity'),
    ('unit_price', 'Unit price', 'unit_price'),
    ('amount', 'Amount', 'amount'),
    ('vat_category', 'VAT', 'vat_category'),
    ('vat_rate', 'VAT rate', 'vat_rate'),
    ('unit_of_measure_id', 'UOM', 'uom_display'),
    ('delivery_date', 'Delivery date', 'delivery_date'),
    ('delivery_site_id', 'Delivery site', 'delivery_site_name'),
    ('wt_id', 'WT', 'wt_code'),
    ('line_status', 'Line status', 'line_status'),
)


def _by_line_id(lines):
    """Index lines by their SalesOrderItem id.

    Line identity is the ROW ID, never content or position. Earlier designs
    guessed correspondence from the product plus list position; both were wrong.
    Content-matching breaks the moment any field changes, and position-matching
    fabricates edits whenever an insert or delete happens anywhere but the tail
    -- e.g. removing the first of two tranches reported a phantom edit on the
    untouched survivor and attributed the removal to the wrong quantity. An id
    is unambiguous, survives reordering for free, and needs no heuristic.

    This is why the amend route UPDATES lines in place instead of deleting and
    rebuilding them (see Task 6): the rebuild would issue new ids every save and
    destroy the only stable identity these rows have.
    """
    return {line.get('line_id'): line
            for line in lines if line.get('line_id') is not None}


def _line_label(line):
    code = line.get('product_code') or '?'
    name = line.get('product_name') or ''
    return f'{code} - {name}'.strip().rstrip('-').strip()


def summarize_change(prev, new):
    """Diff two snapshots into a render-ready change list."""
    changes = []

    prev_h = prev.get('header', {})
    new_h = new.get('header', {})
    for field, label in HEADER_FIELDS.items():
        if field in _HEADER_FIELDS_NOT_SUMMARISED:
            continue
        old_v, new_v = prev_h.get(field), new_h.get(field)
        if old_v != new_v:
            changes.append({'kind': 'header', 'field': label,
                            'old': old_v, 'new': new_v})

    prev_lines = _by_line_id(prev.get('lines', []))
    new_lines = _by_line_id(new.get('lines', []))

    # Matched by id -- diff every summarised field.
    for line_id, new_line in new_lines.items():
        prev_line = prev_lines.get(line_id)
        if prev_line is None:
            changes.append({'kind': 'added', 'line': _line_label(new_line),
                            'old': None, 'new': new_line.get('quantity')})
            continue
        for compare_field, label, display_field in SUMMARISED_LINE_FIELDS:
            if prev_line.get(compare_field) == new_line.get(compare_field):
                continue
            old_v = prev_line.get(display_field)
            new_v = new_line.get(display_field)
            if compare_field == 'quantity':
                changes.append({'kind': 'qty', 'line': _line_label(new_line),
                                'old': old_v, 'new': new_v})
            else:
                changes.append({'kind': 'line_field',
                                'line': _line_label(new_line), 'field': label,
                                'old': old_v, 'new': new_v})

    for line_id, prev_line in prev_lines.items():
        if line_id not in new_lines:
            changes.append({'kind': 'removed', 'line': _line_label(prev_line),
                            'old': prev_line.get('quantity'), 'new': None})

    return {'changes': changes}


def latest_revision(so_id):
    return (SalesOrderRevision.query
            .filter_by(sales_order_id=so_id)
            .order_by(SalesOrderRevision.revision_number.desc())
            .first())


def write_revision(so, user_id, reason=None, authorizing_po=None):
    """Append the next revision for *so*. Adds to the session; does NOT commit."""
    prev = latest_revision(so.id)
    next_number = 0 if prev is None else prev.revision_number + 1

    snapshot = build_snapshot(so)
    summary = None
    if prev is not None:
        summary = json.dumps(summarize_change(json.loads(prev.snapshot_json), snapshot))

    rev = SalesOrderRevision(
        sales_order_id=so.id,
        revision_number=next_number,
        snapshot_json=json.dumps(snapshot),
        change_summary=summary,
        reason=reason,
        authorizing_po_number=authorizing_po,
        amended_by_id=user_id,
        branch_id=so.branch_id,
    )
    db.session.add(rev)
    return rev
