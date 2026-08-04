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
# Key -> label shown in the revision history panel. `quantity` is handled
# specially (kind 'qty') so it renders as the headline change it usually is.
SUMMARISED_LINE_FIELDS = {
    'quantity': 'Qty',
    'unit_price': 'Unit price',
    'uom_display': 'UOM',
    'delivery_date': 'Delivery date',
    # Resolved NAMES, never raw FK integers -- "Delivery site: 3 -> 5" is
    # meaningless to a reader, and this text is printed on a factory-floor slip.
    'delivery_site_name': 'Delivery site',
    'vat_category': 'VAT',
    'wt_code': 'WT',
    'line_status': 'Line status',
}


def _line_identity(line):
    """Everything summarised about a line, as a comparable tuple.

    Two lines with equal identity are the SAME commitment and must be treated as
    unchanged rather than paired against a line that did change.
    """
    return tuple(line.get(f) for f in SUMMARISED_LINE_FIELDS)


def _product_key(line):
    """Which product a line commits us to."""
    return line.get('product_id') or line.get('product_code')


def _group_by_product(lines):
    """Group lines by product, preserving their order within each group.

    One product legitimately appears on SEVERAL lines -- per-line delivery_date
    and delivery_site_id exist precisely so a product can ship in tranches. A
    plain {product: line} dict silently collapses those to the last one and
    loses real changes, so lines are grouped and then paired positionally
    within each group.
    """
    groups = {}
    for line in lines:
        groups.setdefault(_product_key(line), []).append(line)
    return groups


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

    prev_groups = _group_by_product(prev.get('lines', []))
    new_groups = _group_by_product(new.get('lines', []))

    for key, new_lines in new_groups.items():
        remaining_prev = list(prev_groups.get(key, []))

        # PASS 1 -- consume lines that are identical across every summarised
        # field. An UNCHANGED line must never be paired against a changed one,
        # or it masquerades as an edit. Purely positional pairing produced
        # exactly that: removing the FIRST of two tranches reported a fabricated
        # "3000 -> 2000" edit on the surviving line plus a removal attributed to
        # the wrong quantity, and inserting a tranche mid-list reported the new
        # quantity as an edit while "added" carried the OLD one.
        changed_new = []
        for new_line in new_lines:
            match = next((p for p in remaining_prev
                          if _line_identity(p) == _line_identity(new_line)), None)
            if match is not None:
                remaining_prev.remove(match)
            else:
                changed_new.append(new_line)

        # PASS 2 -- whatever genuinely differs, paired positionally.
        for i, new_line in enumerate(changed_new):
            if i >= len(remaining_prev):
                changes.append({'kind': 'added', 'line': _line_label(new_line),
                                'old': None, 'new': new_line.get('quantity')})
                continue
            prev_line = remaining_prev[i]
            for field, label in SUMMARISED_LINE_FIELDS.items():
                old_v, new_v = prev_line.get(field), new_line.get(field)
                if old_v == new_v:
                    continue
                if field == 'quantity':
                    changes.append({'kind': 'qty', 'line': _line_label(new_line),
                                    'old': old_v, 'new': new_v})
                else:
                    changes.append({'kind': 'line_field',
                                    'line': _line_label(new_line), 'field': label,
                                    'old': old_v, 'new': new_v})

        for prev_line in remaining_prev[len(changed_new):]:
            changes.append({'kind': 'removed', 'line': _line_label(prev_line),
                            'old': prev_line.get('quantity'), 'new': None})

    for key, prev_lines in prev_groups.items():
        if key in new_groups:
            continue
        for prev_line in prev_lines:
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
