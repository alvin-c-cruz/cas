"""Shared amendment validation.

Generalised from app/sales_orders/revisions.py::validate_amendment, which remains
the working reference for Sales Orders. Every rule here exists because it failed
in production once; see the invariant comments before simplifying anything.

Nothing in this module raises or mutates -- the route flashes what it returns and
re-renders, so a crafted POST must produce messages, not a 500.
"""
from decimal import Decimal, InvalidOperation

# SQLite does NOT enforce Numeric precision, so an out-of-range value is stored
# verbatim: Decimal('1E+9999') lands in the row as `inf`, and every later
# open-quantity computation on that line is then infinite. The column bound is
# not a bound at all unless this guard applies it.
MAX_LINE_QUANTITY = Decimal('99999999999.9999')


class _OutOfRange:
    """Distinct from None. None means 'could not be parsed at all'; this means
    'parsed fine, but refused as out of range'. Overloading None for both made
    the per-item loop report a value it had already rejected as unreadable --
    a user-facing lie: it read fine, it was simply too large."""

    def __repr__(self):
        return '<OUT_OF_RANGE>'


OUT_OF_RANGE = _OutOfRange()


def parse_submission(new_lines, id_key):
    """(submitted, errors) from raw POSTed line JSON.

    `submitted` maps existing line id -> Decimal | None | OUT_OF_RANGE.
    Lines with no id are new rows and are omitted: they have no existing row to guard.

    Keyed PER ROW on `id_key`, never aggregated per product. An order may
    legitimately carry several lines of one product; an earlier Sales Order version
    aggregated per product and compared that total against every line sharing it, so
    [row A -> 0, row B -> 5000] passed -- a fully-consumed row could be zeroed while a
    sibling absorbed the number. Verified exploitable. Per-row keying makes that shape
    unrepresentable. VALIDATION MUST MIRROR APPLICATION: the applier must key on the
    same identity.
    """
    submitted = {}
    errors = []

    for line in (new_lines or []):
        # new_lines comes straight from json.loads(request.form[...]), so it can be
        # any JSON shape at all. Anything that is not an object is malformed input.
        if not isinstance(line, dict):
            errors.append('Malformed submission: expected a line object. '
                          'Reload the document and try again.')
            continue

        raw_id = line.get(id_key)
        try:
            item_id = int(raw_id) if raw_id not in (None, '', 'null') else None
        except (ValueError, TypeError):
            # Unparseable id -- treat as a NEW line rather than raising.
            item_id = None
        if item_id is None:
            continue

        raw_qty = line.get('quantity')
        try:
            qty = Decimal(str(raw_qty)) if raw_qty not in (None, '', 'null') else None
        except (InvalidOperation, TypeError, ValueError):
            # Unreadable stays None -- NOT 0. Zero is the most destructive value
            # here, and the applier writes NULL for the same garbage.
            qty = None
        # Decimal accepts 'NaN'/'Infinity' happily; a later ordered comparison
        # against a quiet NaN signals InvalidOperation -- a 500, not a refusal.
        if qty is not None and not qty.is_finite():
            qty = None
        # is_finite() does NOT catch this: Decimal('1E+9999') is perfectly finite,
        # merely far larger than the column can hold.
        elif qty is not None and abs(qty) > MAX_LINE_QUANTITY:
            errors.append('Quantity %s is out of range (maximum %s).'
                          % (qty, MAX_LINE_QUANTITY))
            qty = OUT_OF_RANGE

        if item_id in submitted:
            errors.append('Malformed submission: two lines target the same original '
                          'row (id %s). Reload the document and try again.' % item_id)
            continue
        submitted[item_id] = qty

    return submitted, errors
