"""Layout declaration for the Purchase Order pre-printed print designer.

Only this document's identity lives here: its setting key, its fields, its line
columns, and where they sit by default. All behaviour -- canvas bounds, font
allow-list, clamping, sanitisation, per-branch persistence and auditing -- comes
from app.common.preprinted_base, so this file is a declaration rather than a
ninth copy of a 275-line module.
"""
from app.common.preprinted_base import build_layout_api

LAYOUT_SETTING_KEY = 'po_preprinted_layout'

FIELD_KEYS = [
    'po_no', 'order_date', 'expected_date', 'vendor_name', 'vendor_tin',
    'vendor_address', 'payment_terms', 'reference', 'purpose', 'vat_treatment',
    'total_amount',
    # Per-ORDER signatories. Positioned FIELDS rather than static overlay text
    # (the TEXT_KEYS other documents use) precisely because the value differs per
    # order -- it is typed on the form and carried forward from this purchaser's
    # own last PO, not a fixed label printed in the same place every time.
    'prepared_by', 'checked_by', 'approved_by',
]

FIELD_LABELS = {
    'po_no': 'PO No.',
    'order_date': 'Order Date',
    'expected_date': 'Expected Date',
    'vendor_name': 'Vendor',
    'vendor_tin': 'TIN',
    'vendor_address': 'Address',
    'payment_terms': 'Terms',
    'reference': 'Reference',
    'purpose': 'Purpose',
    'vat_treatment': 'VAT Treatment',
    'total_amount': 'Total Amount',
    'prepared_by': 'Prepared by',
    'checked_by': 'Checked by',
    'approved_by': 'Approved by',
}

COLUMN_KEYS = ['line_number', 'product', 'description', 'quantity', 'uom',
               'unit_price', 'amount']

COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'description': 'Description',
    'quantity': 'Qty',
    'uom': 'UOM',
    'unit_price': 'Unit Price',
    'amount': 'Amount',          # bare 'Amount' -- this app prints no currency symbol here
}

# Owner-approved mockup: docs/mockups/2026-08-15-p2p-preprinted-designer.html.
# Header fields sit in two columns (vendor block at x=60, PO-details block at
# x=620) plus total_amount near the foot of the line-item band. 'w' values are
# a judgment call the mockup does not give explicit widths for -- chosen so
# neither block's fields overlap the other block or run past the canvas:
#   - left block (vendor_name/tin/address, x=60): w=500 -- room for a long
#     vendor name/address, ends at x=560, well clear of the right block at 620.
#   - right block (po_no/order_date/expected_date/payment_terms/reference/
#     vat_treatment, x=620): w=200 -- ends at x=820, inside the safe-margin
#     printable edge (CANVAS_W - SAFE_MARGIN = 864), enough for the longest
#     sample value ("VAT Inclusive"/"Zero-Rated") at 11px Courier New.
#   - total_amount (x=700): w=150 -- ends at x=850, also inside the 864 safe
#     margin, enough for a right-aligned peso amount at 13px bold.
DEFAULT_PO_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'vendor_name':     {'x': 60,  'y': 50,  'w': 500, 'fontSize': 12, 'bold': True,  'hidden': False},
        'vendor_tin':      {'x': 60,  'y': 74,  'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
        'vendor_address':  {'x': 60,  'y': 98,  'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
        'po_no':           {'x': 620, 'y': 50,  'w': 200, 'fontSize': 12, 'bold': True,  'hidden': False},
        'order_date':      {'x': 620, 'y': 74,  'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'expected_date':   {'x': 620, 'y': 98,  'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'payment_terms':   {'x': 620, 'y': 122, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'reference':       {'x': 620, 'y': 146, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'vat_treatment':   {'x': 620, 'y': 170, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        # Sits on the LEFT, just above the line-item band (y=300), because it
        # captions the items rather than belonging to the vendor/order block on
        # the right. Bold, matching how the legacy form printed it.
        'purpose':         {'x': 60,  'y': 274, 'w': 500, 'fontSize': 11, 'bold': True,  'hidden': False},
        'total_amount':    {'x': 700, 'y': 430, 'w': 150, 'fontSize': 13, 'bold': True,  'hidden': False},
        # Signature band, below the totals. Geometry is a STARTING POINT only --
        # every client nudges these to their own stationery in the layout
        # designer, which is what it exists for.
        'prepared_by':     {'x': 60,  'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'checked_by':      {'x': 320, 'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'approved_by':     {'x': 580, 'y': 500, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    },
    # Line items: each column is INDEPENDENTLY positioned (its own x) so it can
    # line up with the pre-printed column boxes; all columns share the band top
    # (y) and rowHeight so rows stay aligned. No header row.
    'lineItems': {
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
    },
    'extras': [],
    'texts': {
        'preparer': 'Prepared by:',
        'checker': 'Checked by:',
        'approver': 'Approved by:',
    },
}

sanitize_layout, get_layout, save_layout = build_layout_api(
    LAYOUT_SETTING_KEY, FIELD_KEYS, DEFAULT_PO_PREPRINTED_LAYOUT,
    audit_module='purchase_orders', audit_identifier=LAYOUT_SETTING_KEY)
