"""Layout model for the Delivery Receipt pre-printed print designer.

Faithful clone of the Sales Order pre-printed layout, adapted to the DR record.
The whole layout is one JSON value in an app_settings row. Everything is sanitized
on read AND write against these defaults, so stored or POSTed JSON can never inject
unknown keys, out-of-range numbers, or an unlisted font, and a layout saved before a
new field/column existed still renders that field/column at its default.

Two fields (packing_notes / schedule_notes -- RIC's legacy "Stacking" / "Production
Date" free-text blocks) hold MULTI-LINE document data. They use the exact same box
shape as every other field (x/y/fontSize/bold/hidden) -- the layout JSON only ever
describes WHERE/HOW something prints, never WHAT; multi-line rendering is a
template-only concern (see MULTILINE_FIELD_KEYS). The runaway-textarea risk is
bounded separately, server-side, on the DOCUMENT's own trusted text via
cap_note_lines() -- independent of and never part of the client-submitted layout
JSON sanitized below.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'dr_preprinted_layout'

# Dot-matrix continuous-form stock: 9.5in x 10.5in. At 96dpi (CSS px) that is the
# canvas size, so what is dragged on screen maps 1:1 to the printed form.
CANVAS_W = 912      # 9.5in  @96dpi
CANVAS_H = 1008     # 10.5in @96dpi
SAFE_MARGIN = 48   # printable inset (tractor-feed margin); element x is clamped inside it
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 912
ROW_MIN, ROW_MAX = 8, 80      # line-item row height (px)

# Font picker, grouped for the <select> (optgroups). Monospace faces rasterize
# cleanest on a dot-matrix printer (browsers print in graphics/raster mode, so the
# CSS font DOES reach the output), so they lead. Every entry ends in a generic family
# to cap silent fallback when a face is not installed on the client PC. Windows-first,
# since RIC prints from Windows. No @font-face / OCR font files (self-contained app).
FONT_GROUPS = [
    ('Dot-matrix friendly', [
        '"Courier New", Courier, monospace',
        'Consolas, "Courier New", monospace',
        '"Lucida Console", Monaco, monospace',
    ]),
    ('Standard', [
        'Arial, sans-serif',
        'Calibri, Candara, "Segoe UI", sans-serif',
        'Tahoma, Geneva, sans-serif',
        '"Trebuchet MS", Tahoma, sans-serif',
        'Verdana, Geneva, sans-serif',
        '"Times New Roman", Times, serif',
        'Georgia, serif',
    ]),
]
# Flat allow-list -- the sanitizer's exact-string guard reads this.
ALLOWED_FONTS = [f for _label, _fonts in FONT_GROUPS for f in _fonts]

FIELD_KEYS = [
    'dr_no', 'delivery_date', 'so_no', 'customer_po', 'status',
    'customer_name', 'customer_tin', 'customer_address', 'vendor_code', 'salesperson',
    'remarks', 'product_code', 'packing_notes', 'schedule_notes',
    'checked_by', 'carrier', 'approved_by',
]

# Friendly names for the per-field show/hide strip.
FIELD_LABELS = {
    'dr_no': 'DR No.',
    'delivery_date': 'Delivery Date',
    'so_no': 'SO No.',
    'customer_po': 'PO No.',
    'status': 'Status',
    'customer_name': 'Customer',
    'customer_tin': 'TIN',
    'customer_address': 'Address',
    'vendor_code': "Customer's Code for Us",
    'salesperson': 'Salesperson',
    'remarks': 'Remarks',
    # Single value (first line's customer product code) -- NOT the per-line
    # customer_product_code column below; matches legacy's product_code_description.
    'product_code': "Product Code (first line)",
    'packing_notes': 'Packing / Lot Breakdown',
    'schedule_notes': 'Delivery Schedule (BO/CO)',
    'checked_by': 'Checked By',
    'carrier': 'Carrier',
    'approved_by': 'Approved By',
}

# Subset of FIELD_KEYS whose rendered VALUE may contain newlines. Rendering-only
# distinction (adds the `pp-multiline` CSS class in the print template) -- these
# keys use the identical box shape (x/y/fontSize/bold/hidden) as every other field;
# nothing new is stored or accepted from the client for them.
MULTILINE_FIELD_KEYS = ('remarks', 'packing_notes', 'schedule_notes')

# Server-side cap on rendered note lines -- bounds the DOCUMENT's own trusted DB
# text (packing_notes/schedule_notes), never client-submitted layout JSON. Applied
# by the print_dr view before the text reaches the template.
MAX_NOTE_LINES = 10


def cap_note_lines(text):
    """First MAX_NOTE_LINES lines of `text` (CRLF normalized), or '' if blank."""
    if not text:
        return ''
    return '\n'.join(text.replace('\r\n', '\n').split('\n')[:MAX_NOTE_LINES])


COLUMN_KEYS = ['line_number', 'quantity', 'uom', 'customer_product_code', 'product']  # no pricing on a DR

# Header labels for the line-item columns (presentation; keyed by COLUMN_KEYS).
COLUMN_LABELS = {
    'line_number': '#',
    'quantity': 'Qty Delivered',
    'uom': 'UOM',
    'customer_product_code': "Customer's Code",
    'product': 'Product',
}

ALLOWED_PAPERS = ('continuous', 'letter')

# Canvas + @page size per paper (px @96dpi / CSS inches). Continuous = the dot-matrix
# 9.5x10.5in fan-fold stock (shows tractor-hole margin guides); letter = 8.5x11in cut
# sheet (no guides).
PAPER_SIZES = {
    'continuous': {'w': 912, 'h': 1008, 'css': '9.5in 10.5in'},
    'letter':     {'w': 816, 'h': 1056, 'css': '8.5in 11in'},
}
PAPER_LABELS = {
    'continuous': '9.5 x 10.5 continuous paper',
    'letter':     'Letter 8.5 x 11',
}

# Date format for the delivery date. key -> strftime. The dropdown labels are
# generated from a sample date so they always match. The JS live-preview mirrors
# these keys (so_preprinted_designer.js::fmtDate -- shared across all doc types).
DATE_FORMATS = {
    'long':   '%d %B %Y',
    # Legacy's long_date() (application/extensions.py): always this exact shape,
    # hardcoded, no other option -- this is the DR default so a fresh install
    # matches legacy's printed date verbatim ("December 19, 2025").
    'full':   '%B %d, %Y',
    'medium': '%b %d, %Y',
    'us':     '%m/%d/%Y',
    'eu':     '%d/%m/%Y',
    'iso':    '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50   # duplicated field copies cap

# Free-text, LAYOUT-ONLY signature elements (not tied to the DR record). Editable
# in the designer; the same text prints on every DR.
TEXT_KEYS = ['prepared_by', 'released_by', 'received_by']
TEXT_LABELS = {'prepared_by': 'Prepared by', 'released_by': 'Released by',
               'received_by': 'Received by'}
TEXT_MAXLEN = 200

DEFAULT_DR_PREPRINTED_LAYOUT = {
    # Positions below are converted 1:1 from RIC's legacy print.html (rowell1968's
    # delivery_receipt/print.html), whose absolute-positioned fields are declared in
    # mm (96dpi: 1mm = 3.7795px). Every legacy field is wrapped in <strong> (bold=True)
    # and the page font is "Calibri, Arial, sans-serif" -- reproduced here as closely
    # as this designer's allow-listed fonts permit. `customer_business_style` (legacy's
    # DTI trade-name field) is confirmed "N/A" for every legacy customer row -- unused
    # in practice, not modeled here.
    'paper': 'continuous',
    # 'full' ('%B %d, %Y' -> "December 19, 2025") matches legacy's long_date()
    # exactly -- legacy's own DR date format, hardcoded, no other option there.
    'dateFormat': 'full',
    'extras': [],
    # Generic signature labels, NOT tied to the checked_by/carrier/approved_by DATA
    # fields below (legacy prints the actual names/carrier there, not a blank "sign
    # here" line -- there is no such concept on the legacy slip at all). Kept
    # available but hidden by default and moved off that row to avoid overlapping
    # the real data fields; enable in the designer if a physical signature line is
    # still wanted in addition to the printed names.
    'texts': [
        {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 57,  'y': 650, 'fontSize': 13, 'bold': True, 'hidden': True},
        {'id': 'released_by', 'text': 'Released by:', 'x': 246, 'y': 650, 'fontSize': 13, 'bold': True, 'hidden': True},
        {'id': 'received_by', 'text': 'Received by (Signature / Date):', 'x': 397, 'y': 650, 'fontSize': 13, 'bold': True, 'hidden': True},
    ],
    'page': {'fontFamily': 'Calibri, Candara, "Segoe UI", sans-serif'},
    'fields': {
        'dr_no':            {'x': 699, 'y': 79,  'fontSize': 13, 'bold': True},
        'delivery_date':    {'x': 635, 'y': 181, 'fontSize': 13, 'bold': True},
        'so_no':            {'x': 654, 'y': 223, 'fontSize': 13, 'bold': True},
        'customer_po':      {'x': 654, 'y': 200, 'fontSize': 13, 'bold': True},
        # Not on the legacy slip at all -- hidden by default so a fresh install
        # matches legacy exactly; toggle on in the designer if wanted.
        'status':           {'x': 654, 'y': 270, 'fontSize': 11, 'bold': True, 'hidden': True},
        'customer_name':    {'x': 155, 'y': 178, 'fontSize': 18, 'bold': True},
        'customer_tin':     {'x': 106, 'y': 223, 'fontSize': 13, 'bold': True},
        'customer_address': {'x': 125, 'y': 204, 'fontSize': 12, 'bold': True},
        'vendor_code':      {'x': 136, 'y': 246, 'fontSize': 13, 'bold': True},
        'salesperson':      {'x': 673, 'y': 242, 'fontSize': 13, 'bold': True},
        # Legacy renders `notes` right after the last line item (same column slot as
        # product name), before the stacking/production_date blocks below it.
        'remarks':          {'x': 321, 'y': 340, 'fontSize': 14, 'bold': True},
        # Legacy's product_code_description: margin_left=90mm (~340px), printed once
        # right below notes/remarks -- the FIRST line's customer product code only,
        # not one per line (see FIELD_LABELS note above).
        'product_code':     {'x': 321, 'y': 395, 'fontSize': 14, 'bold': True},
        # Legacy positions these via CSS margin in normal document flow, right below
        # the line items (not a fixed absolute slot) -- these x/y are a reasonable
        # starting point for a typical few-line order; drag to fit longer orders.
        'packing_notes':    {'x': 321, 'y': 450, 'fontSize': 14, 'bold': True},
        'schedule_notes':   {'x': 321, 'y': 505, 'fontSize': 14, 'bold': True},
        # Legacy's checked_by/carrier/approved_by row (top=149mm, left=15/65/105mm).
        'checked_by':       {'x': 57,  'y': 563, 'fontSize': 13, 'bold': True},
        'carrier':          {'x': 246, 'y': 563, 'fontSize': 13, 'bold': True},
        'approved_by':      {'x': 397, 'y': 563, 'fontSize': 13, 'bold': True},
    },
    # Line items: each column is INDEPENDENTLY positioned (its own x) so it can line
    # up with the pre-printed column boxes; all columns share the band top (y) and
    # rowHeight so rows stay aligned. No header row. Matches legacy's exact row order:
    # quantity, measure(uom), product_code (the CUSTOMER's own code, Product.customer_code
    # -- not CAS's internal Product.code), product_name. CAS has no row-numbering
    # column at all, so line_number is hidden by default (legacy doesn't show one).
    'lineItems': {
        'y': 295, 'rowHeight': 20, 'fontSize': 14, 'bold': True,
        'columns': [
            {'key': 'line_number',           'x': 30,  'visible': False, 'width': 30},
            {'key': 'quantity',              'x': 57,  'visible': True,  'width': 94},
            {'key': 'uom',                   'x': 151, 'visible': True,  'width': 144},
            {'key': 'customer_product_code', 'x': 295, 'visible': True,  'width': 76},
            {'key': 'product',               'x': 371, 'visible': True,  'width': 378},
        ],
    },
}


def _clamp(value, lo, hi, fallback):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, n))


def _clean_box(raw, default):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'x': _clamp(raw.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
        'hidden': bool(raw.get('hidden', default.get('hidden', False))),
    }


def _clean_columns(raw):
    raw = raw if isinstance(raw, list) else []
    by_key = {c.get('key'): c for c in raw if isinstance(c, dict) and c.get('key') in COLUMN_KEYS}
    defaults = {c['key']: c for c in DEFAULT_DR_PREPRINTED_LAYOUT['lineItems']['columns']}
    ordered_keys = [c['key'] for c in raw
                    if isinstance(c, dict) and c.get('key') in COLUMN_KEYS]
    # keep first-seen order, then append any known column the input omitted
    seen, order = set(), []
    for k in ordered_keys + COLUMN_KEYS:
        if k not in seen:
            seen.add(k)
            order.append(k)
    out = []
    for k in order:
        src = by_key.get(k, {})
        d = defaults[k]
        out.append({
            'key': k,
            'x': _clamp(src.get('x'), 0, CANVAS_W, d['x']),
            'visible': bool(src.get('visible', d['visible'])),
            'width': _clamp(src.get('width'), WIDTH_MIN, WIDTH_MAX, d['width']),
        })
    return out


def _clean_extras(raw):
    """Duplicated field copies: each references a FIELD_KEYS key + its own position/style."""
    raw = raw if isinstance(raw, list) else []
    out = []
    for e in raw[:MAX_EXTRAS]:
        if not isinstance(e, dict) or e.get('key') not in FIELD_KEYS:
            continue
        out.append({
            'key': e['key'],
            'x': _clamp(e.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, 0),
            'y': _clamp(e.get('y'), 0, CANVAS_H, 0),
            'fontSize': _clamp(e.get('fontSize'), FONT_MIN, FONT_MAX, 11),
            'bold': bool(e.get('bold', False)),
        })
    return out


def sanitize_layout(raw):
    """Return a fully-populated, validated layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_DR_PREPRINTED_LAYOUT
    paper = raw.get('paper') if raw.get('paper') in ALLOWED_PAPERS else d['paper']
    date_fmt = raw.get('dateFormat') if raw.get('dateFormat') in ALLOWED_DATE_FORMATS else d['dateFormat']
    font = (raw.get('page') or {}).get('fontFamily')
    page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS}
    raw_li = raw.get('lineItems') if isinstance(raw.get('lineItems'), dict) else {}
    dli = d['lineItems']
    line_items = {
        'y': _clamp(raw_li.get('y'), 0, CANVAS_H, dli['y']),
        'rowHeight': _clamp(raw_li.get('rowHeight'), ROW_MIN, ROW_MAX, dli['rowHeight']),
        'fontSize': _clamp(raw_li.get('fontSize'), FONT_MIN, FONT_MAX, dli['fontSize']),
        'bold': bool(raw_li.get('bold', dli['bold'])),
        'columns': _clean_columns(raw_li.get('columns')),
    }
    return {'paper': paper, 'dateFormat': date_fmt, 'extras': _clean_extras(raw.get('extras')),
            'texts': clean_texts(raw.get('texts'), DEFAULT_DR_PREPRINTED_LAYOUT['texts']),
            'page': page, 'fields': fields, 'lineItems': line_items}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_DR_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_DR_PREPRINTED_LAYOUT)


def save_layout(raw, username, branch_id=None):
    """Sanitize, persist (per branch), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='delivery_receipts', action='update', record_id=None,
              record_identifier='dr_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'Pre-printed layout updated (branch {branch_id})')
    return clean
