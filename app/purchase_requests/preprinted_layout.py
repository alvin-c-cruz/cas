"""Layout declaration for the Purchase Requisition pre-printed print designer.

Only this document's identity lives here: its setting key, its fields, its line
columns, and where they sit by default. All behaviour -- canvas bounds, font
allow-list, clamping, sanitisation, per-branch persistence and auditing -- comes
from app.common.preprinted_base, so this file is a declaration rather than a
ninth copy of a 275-line module.

A requisition is an internal ask -- no vendor, no money anywhere. Pricing
arrives later, at PO.
"""
from app.common.preprinted_base import (
    CANVAS_W, CANVAS_H, ALLOWED_FONTS, TEXT_KEYS, build_layout_api)

LAYOUT_SETTING_KEY = 'pr_preprinted_layout'

FIELD_KEYS = ['pr_number', 'request_date', 'date_needed', 'reason', 'branch']

FIELD_LABELS = {
    'pr_number': 'PR No.',
    'request_date': 'Request Date',
    'date_needed': 'Date Needed',
    # 'Note', NOT 'Reason' -- commit 7d1e3d9b renamed this label on the
    # requisition and the printed form must use the module's own word.
    'reason': 'Note',
    'branch': 'Branch',
}

COLUMN_KEYS = ['line_number', 'product', 'description', 'quantity', 'uom']

COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'description': 'Description',
    'quantity': 'Qty',
    'uom': 'UOM',
}

# No owner-approved mockup for PR -- Task 1's mockup covered the Purchase Order
# as the richest case; PR/RR reuse the same canvas mechanics. This geometry is
# derived from PO's approved layout so all three documents stay visually
# aligned: left block (branch/reason, x=60) mirrors PO's left block, right
# block (pr_number/request_date/date_needed, x=620) mirrors PO's right block,
# and the first five line-item columns are PO's own unchanged so PR and PO
# line up on the same stationery family.
DEFAULT_PR_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'branch':        {'x': 60,  'y': 50, 'w': 500, 'fontSize': 12, 'bold': True,  'hidden': False},
        'reason':        {'x': 60,  'y': 74, 'w': 500, 'fontSize': 11, 'bold': False, 'hidden': False},
        'pr_number':     {'x': 620, 'y': 50, 'w': 200, 'fontSize': 12, 'bold': True,  'hidden': False},
        'request_date':  {'x': 620, 'y': 74, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
        'date_needed':   {'x': 620, 'y': 98, 'w': 200, 'fontSize': 11, 'bold': False, 'hidden': False},
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
    LAYOUT_SETTING_KEY, FIELD_KEYS, DEFAULT_PR_PREPRINTED_LAYOUT,
    audit_module='purchase_requests', audit_identifier=LAYOUT_SETTING_KEY)
