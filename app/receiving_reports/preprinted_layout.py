"""Layout declaration for the Receiving Report pre-printed print designer.

Only this document's identity lives here: its setting key, its fields, its line
columns, and where they sit by default. All behaviour -- canvas bounds, font
allow-list, clamping, sanitisation, per-branch persistence and auditing -- comes
from app.common.preprinted_base, so this file is a declaration rather than a
ninth copy of a 275-line module.

An RR is receipt evidence against its PO. `ReceivingReportItem` stores only
line_number, a product_id snapshot and received_quantity -- description,
ordered_qty and uom come through the purchase_order_item FK at render time.
That is a rendering rule (Task 7), not something declared here.
"""
from app.common.preprinted_base import build_layout_api

LAYOUT_SETTING_KEY = 'rr_preprinted_layout'

FIELD_KEYS = ['rr_number', 'receipt_date', 'vendor_name', 'remarks']

FIELD_LABELS = {
    'rr_number': 'RR No.',
    'receipt_date': 'Receipt Date',
    'vendor_name': 'Vendor',
    'remarks': 'Remarks',
}

# `po_number` is a COLUMN, not a header field: one receipt may settle several of
# a vendor's orders (multi-PO receiving, Task 4), so no single header box can
# print "the" PO number -- each line carries its own, derived through
# ReceivingReportItem.po_number (app/receiving_reports/models.py).
COLUMN_KEYS = ['line_number', 'product', 'description', 'po_number',
               'ordered_qty', 'received_quantity', 'uom']

COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'description': 'Description',
    'po_number': 'PO No.',
    'ordered_qty': 'Ordered',
    'received_quantity': 'Received',
    'uom': 'UOM',
}

# No owner-approved mockup for RR -- Task 1's mockup covered the Purchase Order
# as the richest case; PR/RR reuse the same canvas mechanics. This geometry is
# derived from PO's approved layout so all three documents stay visually
# aligned: left block (vendor_name/remarks, x=60) mirrors PO's left block,
# right block (rr_number/receipt_date, x=620) mirrors PO's right block, and
# the first three line-item columns are PO's own unchanged so RR and PO line
# up on the same stationery family.
DEFAULT_RR_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'vendor_name':   {'x': 60,  'y': 50, 'w': 500, 'fontSize': 12, 'bold': True,  'hidden': False},
        'remarks':       {'x': 60,  'y': 74, 'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
        'rr_number':     {'x': 620, 'y': 50, 'w': 200, 'fontSize': 12, 'bold': True,  'hidden': False},
        'receipt_date':  {'x': 620, 'y': 74, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
    },
    # Line items: each column is INDEPENDENTLY positioned (its own x) so it can
    # line up with the pre-printed column boxes; all columns share the band top
    # (y) and rowHeight so rows stay aligned. No header row.
    #
    # `po_number` is appended AFTER `uom` (x=666) rather than slotted between
    # `description` (ends 460) and `ordered_qty` (starts 468) -- that gap is
    # only 8px, not enough room for a PO number box. Placing it after `uom`
    # (which ends at 660) leaves a 6px gap to it and it ends at 776, well
    # inside the safe-margin printable edge (CANVAS_W - SAFE_MARGIN = 864).
    #
    # Its width is 110, not the 80 the band strictly needs. `.pp-cell` is
    # `overflow: hidden; white-space: nowrap`, so a number too long for its box
    # is CLIPPED SILENTLY on a printed document -- there is no ellipsis and no
    # warning. At fontSize 10 in Courier New (~0.6em advance) 80px holds ~13
    # characters, which fits a generated 5-digit serial but truncates a legacy
    # prefixed one (`RR-2026-07-0030`, 15 chars). 110px holds ~18 and still
    # leaves 88px of slack to the safe margin, so the headroom is free.
    'lineItems': {
        'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number',       'x': 56,  'visible': True, 'width': 30},
            {'key': 'product',           'x': 92,  'visible': True, 'width': 200},
            {'key': 'description',       'x': 300, 'visible': True, 'width': 160},
            {'key': 'ordered_qty',       'x': 468, 'visible': True, 'width': 60},
            {'key': 'received_quantity', 'x': 534, 'visible': True, 'width': 70},
            {'key': 'uom',               'x': 610, 'visible': True, 'width': 50},
            {'key': 'po_number',         'x': 666, 'visible': True, 'width': 110},
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
    LAYOUT_SETTING_KEY, FIELD_KEYS, DEFAULT_RR_PREPRINTED_LAYOUT,
    audit_module='receiving_reports', audit_identifier=LAYOUT_SETTING_KEY)
