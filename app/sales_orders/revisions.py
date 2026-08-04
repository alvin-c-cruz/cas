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
    'salesperson_name': 'Salesperson',
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
        # Decimal('-0') == Decimal('0') is True but they would serialise as
        # '-0' and '0' -- equal values with unequal strings is precisely the
        # failure mode this normalisation exists to prevent.
        if value == 0:
            value = abs(value)
        # normalize() collapses trailing zeros; format(..., 'f') avoids the
        # scientific notation normalize() produces for large integral values
        # (Decimal('3000').normalize() is Decimal('3E+3')).
        return format(value.normalize(), 'f')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _money(value):
    """DISPLAY form for money: always 2 decimal places.

    Deliberately separate from _s(). _s canonicalises for COMPARISON, which
    means Decimal('4.20') collapses to '4.2' -- correct for detecting a change,
    wrong on a printed job order slip where money must read as 4.20.
    """
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')


def build_snapshot(so):
    """Complete order state -- header + all lines -- as of right now."""
    header = {k: _s(getattr(so, k, None)) for k in HEADER_FIELDS}
    # Unlike customer (which has customer_name alongside the suppressed
    # customer_id) salesperson had no readable companion, so a reassignment
    # could not be reported at all.
    header['salesperson_name'] = (so.salesperson.full_name
                                  if so.salesperson else None)
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
        # Composite so a free-text uom_text change is detected even when the FK
        # is null on both sides.
        row['uom_key'] = '%s|%s' % (item.unit_of_measure_id or '',
                                    item.uom_text or '')
        # Money is COMPARED via _s (canonical) but DISPLAYED at 2 dp.
        row['unit_price_display'] = _money(item.unit_price)
        row['amount_display'] = _money(item.amount)
        lines.append(row)
    return {'header': header, 'lines': lines}


# Line fields whose change is user-meaningful and therefore summarised.
# Key -> label shown in the revision history panel. `quantity` is handled
# specially (kind 'qty') so it renders as the headline change it usually is.
# (compared field, label, display field). The comparison is done on the FIRST
# element and the value shown to the reader comes from the THIRD -- so a change
# is detected on the stable id but rendered as a human-readable name. Two
# delivery sites can share a name (CustomerDeliverySite has no unique constraint
# on (customer_id, name)), so comparing names alone would hide a real change.
SUMMARISED_LINE_FIELDS = (
    # The amend route updates rows IN PLACE, so a line can change product while
    # keeping its id. Without this entry that change is invisible -- and worse,
    # _line_label renders the NEW product beside the OLD quantity.
    ('product_id', 'Product', 'product_name'),
    ('quantity', 'Qty', 'quantity'),
    ('unit_price', 'Unit price', 'unit_price_display'),
    ('amount', 'Amount', 'amount_display'),
    ('vat_category', 'VAT', 'vat_category'),
    ('vat_rate', 'VAT rate', 'vat_rate'),
    # Compared on a composite key: uom_text is a real nullable free-text column
    # used whenever unit_of_measure_id is null, so comparing the id alone makes
    # a 'pcs' -> 'kg' change invisible. "3000 pcs" and "3000 kg" are different
    # manufacturing instructions.
    ('uom_key', 'UOM', 'uom_display'),
    ('delivery_date', 'Delivery date', 'delivery_date'),
    ('delivery_site_id', 'Delivery site', 'delivery_site_name'),
    ('wt_id', 'WT', 'wt_code'),
    ('line_status', 'Line status', 'line_status'),
)

# Fields whose change is fully explained by another reported change. `amount` is
# derived (qty x price) exactly as the header totals are, and the header totals
# are already suppressed for that reason -- reporting it alongside its own
# inputs double-counts one edit.
_DERIVED_LINE_FIELDS = {'amount': ('quantity', 'unit_price')}


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
    indexed = {}
    for line in lines:
        line_id = line.get('line_id')
        if line_id is None:
            # Fail CLOSED. Silently skipping an unidentified line makes the diff
            # under-report: an added line whose row was never flushed would
            # produce an empty change summary on a revision that carries a
            # reason and an authorizing PO. write_revision flushes first so this
            # is unreachable; if it fires, something upstream is wrong.
            raise ValueError(
                'snapshot line has no line_id -- the row was not flushed before '
                'build_snapshot(); write_revision() must flush first')
        indexed[line_id] = line
    return indexed


def _line_label(line):
    code = line.get('product_code') or '?'
    name = line.get('product_name') or ''
    # Do NOT rstrip('-') -- that eats a trailing hyphen from a real product name.
    return f'{code} - {name}' if name else code


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
                            'old': None,
                            'new': (new_line.get('quantity')
                                    or new_line.get('amount_display'))})
            continue
        for compare_field, label, display_field in SUMMARISED_LINE_FIELDS:
            if prev_line.get(compare_field) == new_line.get(compare_field):
                continue
            # Skip a derived field whose own inputs already changed -- otherwise
            # one quantity edit reports twice (Qty and Amount).
            inputs = _DERIVED_LINE_FIELDS.get(compare_field)
            if inputs and any(prev_line.get(f) != new_line.get(f) for f in inputs):
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
                            'old': (prev_line.get('quantity')
                                    or prev_line.get('amount_display')),
                            'new': None})

    return {'changes': changes}


def latest_revision(so_id):
    return (SalesOrderRevision.query
            .filter_by(sales_order_id=so_id)
            .order_by(SalesOrderRevision.revision_number.desc())
            .first())


def write_revision(so, user_id, reason=None, authorizing_po=None):
    """Append the next revision for *so*. Adds to the session; does NOT commit."""
    # Flush first: a line appended but not yet flushed has id None, and the
    # snapshot's identity depends on that id existing.
    db.session.flush()

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
