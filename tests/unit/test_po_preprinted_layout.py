"""The PO layout declares its own identity and inherits behaviour from the base."""
import copy
from collections import defaultdict
from datetime import date

import pytest

from app.common import preprinted_base as base
from app.purchase_orders import preprinted_layout as pl

pytestmark = [pytest.mark.unit, pytest.mark.purchase_orders]

# Currency markers that must never appear in a printed line-item column header --
# this app extracts a currency symbol nowhere in a column header (CAS convention).
CURRENCY_MARKERS = ['₱', '$', '&#8369;']

# The owner-approved mockup's exact default geometry
# (docs/mockups/2026-08-15-p2p-preprinted-designer.html), written out as a
# literal so a future accidental edit to the declaration is caught, not echoed
# back to itself.
EXPECTED_FIELDS = {
    'vendor_name':     {'x': 60,  'y': 50,  'w': 500, 'fontSize': 12, 'bold': True,  'hidden': False},
    'vendor_tin':      {'x': 60,  'y': 74,  'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
    'vendor_address':  {'x': 60,  'y': 98,  'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
    'po_no':           {'x': 620, 'y': 50,  'w': 200, 'fontSize': 12, 'bold': True,  'hidden': False},
    'order_date':      {'x': 620, 'y': 74,  'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'expected_date':   {'x': 620, 'y': 98,  'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'payment_terms':   {'x': 620, 'y': 122, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'reference':       {'x': 620, 'y': 146, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'vat_treatment':   {'x': 620, 'y': 170, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'total_amount':    {'x': 700, 'y': 430, 'w': 150, 'fontSize': 13, 'bold': True,  'hidden': False},
    # Signature band below the totals. A starting point every client nudges to
    # its own stationery in the layout designer.
    'prepared_by':     {'x': 60,  'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'checked_by':      {'x': 320, 'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    'approved_by':     {'x': 580, 'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
}

EXPECTED_LINE_ITEMS = {
    'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
    'columns': [
        {'key': 'line_number', 'x': 56,  'visible': True, 'width': 30},
        {'key': 'product',     'x': 92,  'visible': True, 'width': 200},
        {'key': 'description', 'x': 300, 'visible': True, 'width': 160},
        {'key': 'quantity',    'x': 468, 'visible': True, 'width': 50},
        {'key': 'uom',         'x': 524, 'visible': True, 'width': 50},
        {'key': 'unit_price',  'x': 580, 'visible': True, 'width': 90},
        {'key': 'amount',      'x': 676, 'visible': True, 'width': 100},
    ],
}


def test_it_declares_the_po_setting_key():
    assert pl.LAYOUT_SETTING_KEY == 'po_preprinted_layout'


def test_it_declares_every_po_header_field():
    assert pl.FIELD_KEYS == [
        'po_no', 'order_date', 'expected_date', 'vendor_name', 'vendor_tin',
        'vendor_address', 'payment_terms', 'reference', 'vat_treatment', 'total_amount',
        # Per-order signatories (posig_0001). Positioned FIELDS, not the static
        # TEXT_KEYS other documents use, because the value differs per order.
        'prepared_by', 'checked_by', 'approved_by',
    ]


def test_the_field_labels_are_pinned_exactly():
    """Membership alone (`k in FIELD_LABELS`) lets any label's TEXT drift silently
    -- these are user-visible words on a supplier-facing document."""
    assert pl.FIELD_LABELS == {
        'po_no': 'PO No.',
        'order_date': 'Order Date',
        'expected_date': 'Expected Date',
        'vendor_name': 'Vendor',
        'vendor_tin': 'TIN',
        'vendor_address': 'Address',
        'payment_terms': 'Terms',
        'reference': 'Reference',
        'vat_treatment': 'VAT Treatment',
        'total_amount': 'Total Amount',
        'prepared_by': 'Prepared by',
        'checked_by': 'Checked by',
        'approved_by': 'Approved by',
    }


def test_it_declares_the_po_line_columns():
    assert pl.COLUMN_KEYS == [
        'line_number', 'product', 'description', 'quantity', 'uom', 'unit_price', 'amount',
    ]


def test_the_column_labels_are_pinned_exactly():
    assert pl.COLUMN_LABELS == {
        'line_number': '#',
        'product': 'Product',
        'description': 'Description',
        'quantity': 'Qty',
        'uom': 'UOM',
        'unit_price': 'Unit Price',
        'amount': 'Amount',
    }


def test_no_column_label_carries_a_currency_symbol():
    """This app prints no currency symbol in a column header -- enforced here
    rather than merely commented next to the declaration."""
    for key, label in pl.COLUMN_LABELS.items():
        for marker in CURRENCY_MARKERS:
            assert marker not in label, f'{key} label {label!r} contains a currency marker'


def test_a_foreign_field_is_rejected_by_the_inherited_sanitiser():
    """Control: PO must not accept a Sales Order field. This is what stops one
    document's stored layout leaking into another's."""
    out = pl.sanitize_layout({'fields': {'customer_name': {'x': 10, 'y': 10}}})
    assert 'customer_name' not in out['fields']
    assert set(out['fields']) == set(pl.FIELD_KEYS)


def test_the_default_field_geometry_is_pinned():
    """Pins the full default box (x/y/w/fontSize/bold/hidden) per field against
    the owner-approved mockup, not merely 'inside the canvas'. Also proves all
    ten fields print by default (`hidden` is False everywhere)."""
    assert pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'] == EXPECTED_FIELDS
    for k, box in EXPECTED_FIELDS.items():
        assert box['hidden'] is False, k


def test_the_default_line_items_band_and_columns_are_pinned():
    assert pl.DEFAULT_PO_PREPRINTED_LAYOUT['lineItems'] == EXPECTED_LINE_ITEMS


def test_paper_and_date_format_are_pinned():
    assert pl.DEFAULT_PO_PREPRINTED_LAYOUT['paper'] == 'continuous'
    assert pl.DEFAULT_PO_PREPRINTED_LAYOUT['dateFormat'] == 'long'


def test_the_date_format_renders_the_mockups_date_shape():
    fmt = base.DATE_FORMATS[pl.DEFAULT_PO_PREPRINTED_LAYOUT['dateFormat']]
    assert date(2026, 8, 15).strftime(fmt) == '15 August 2026'


def test_columns_tile_without_overlap_and_stay_on_the_canvas():
    """Derived from the declaration, not hardcoded comparisons -- keeps working
    when a coordinate legitimately changes. Each column's right edge must not
    pass the next column's left edge, and the last column must stay inside the
    safe-margin printable width."""
    columns = pl.DEFAULT_PO_PREPRINTED_LAYOUT['lineItems']['columns']
    ordered = sorted(columns, key=lambda c: c['x'])
    for cur, nxt in zip(ordered, ordered[1:]):
        assert cur['x'] + cur['width'] <= nxt['x'], \
            f"{cur['key']} (x={cur['x']}, w={cur['width']}) overlaps {nxt['key']} (x={nxt['x']})"
    last = ordered[-1]
    assert last['x'] + last['width'] <= base.CANVAS_W - base.SAFE_MARGIN


def test_field_boxes_on_the_same_visual_row_do_not_overlap_horizontally():
    """Derived from the declaration: group fields by their declared y (same
    visual row), then require each row's boxes to be horizontally disjoint.
    Overlap between two individually-valid boxes is exactly what neither this
    file nor the base validator otherwise catches."""
    rows = defaultdict(list)
    for key, box in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'].items():
        rows[box['y']].append((key, box))
    for y, boxes in rows.items():
        if len(boxes) < 2:
            continue
        ordered = sorted(boxes, key=lambda kb: kb[1]['x'])
        for (k1, b1), (k2, b2) in zip(ordered, ordered[1:]):
            assert b1['x'] + b1['w'] <= b2['x'], \
                f"{k1} (x={b1['x']}, w={b1['w']}) overlaps {k2} (x={b2['x']}) on row y={y}"


def test_an_out_of_bounds_default_field_is_rejected_by_the_import_time_validator():
    """`build_layout_api` enforces SAFE_MARGIN <= x <= CANVAS_W - SAFE_MARGIN on
    every declared default field at import time. A deliberately-bad scratch
    declaration (never the real module) must raise ValueError naming the
    offending key -- proving the validator itself, rather than merely relying on
    the fact that the real module happens to import cleanly."""
    bad = copy.deepcopy(pl.DEFAULT_PO_PREPRINTED_LAYOUT)
    bad['fields']['vendor_name']['x'] = base.SAFE_MARGIN - 1
    with pytest.raises(ValueError, match=r"\['vendor_name'\]\['x'\]"):
        base.build_layout_api('scratch_po_layout', pl.FIELD_KEYS, bad,
                              audit_module='purchase_orders', audit_identifier='scratch_po_layout')
