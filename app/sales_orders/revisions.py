"""Snapshot + change-summary services for Sales Order revisions.

build_snapshot / summarize_change are pure: no request context, no session.
write_revision touches the session but never commits -- the caller owns the
transaction so a revision and the order edit that produced it land atomically.
"""
import json

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
    """JSON-safe, exact string form. Decimals keep full precision; dates ISO."""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def build_snapshot(so):
    """Complete order state -- header + all lines -- as of right now."""
    header = {k: _s(getattr(so, k, None)) for k in HEADER_FIELDS}
    lines = []
    for item in sorted(so.line_items, key=lambda i: (i.line_number or 0)):
        row = {}
        for f in LINE_FIELDS:
            row[f] = _s(getattr(item, f, None))
        row['product_code'] = item.product.code if item.product else None
        row['product_name'] = item.product.name if item.product else None
        lines.append(row)
    return {'header': header, 'lines': lines}


def _line_key(line):
    """Identity of a line for diffing: the product it commits us to.

    Keyed on product, NOT line_number -- reordering lines is not a change, and a
    line whose product was swapped must read as removed+added (spec resolved
    edge case 1), which falls out of this key naturally.
    """
    return line.get('product_id') or line.get('product_code')


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

    prev_lines = {_line_key(l): l for l in prev.get('lines', [])}
    new_lines = {_line_key(l): l for l in new.get('lines', [])}

    for key, line in new_lines.items():
        if key not in prev_lines:
            changes.append({'kind': 'added', 'line': _line_label(line),
                            'old': None, 'new': line.get('quantity')})
        elif prev_lines[key].get('quantity') != line.get('quantity'):
            changes.append({'kind': 'qty', 'line': _line_label(line),
                            'old': prev_lines[key].get('quantity'),
                            'new': line.get('quantity')})

    for key, line in prev_lines.items():
        if key not in new_lines:
            changes.append({'kind': 'removed', 'line': _line_label(line),
                            'old': line.get('quantity'), 'new': None})

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
