"""Layout model for the Sales Invoice pre-printed print designer (SI-P-71).

The whole layout is one JSON value in an app_settings row. Everything is sanitized
on read AND write against these defaults, so stored or POSTed JSON can never inject
unknown keys, out-of-range numbers, or an unlisted font, and a layout saved before a
new field/column existed still renders that field/column at its default.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit

LAYOUT_SETTING_KEY = 'sv_preprinted_layout'

# Dot-matrix continuous-form stock: 9.5in x 10.5in. At 96dpi (CSS px) that is the
# canvas size, so what is dragged on screen maps 1:1 to the printed form.
CANVAS_W = 912      # 9.5in  @96dpi
CANVAS_H = 1008     # 10.5in @96dpi
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
# Flat allow-list — the sanitizer's exact-string guard reads this.
ALLOWED_FONTS = [f for _label, _fonts in FONT_GROUPS for f in _fonts]

FIELD_KEYS = [
    'invoice_no', 'invoice_date', 'due_date', 'terms',
    'customer_name', 'customer_tin', 'customer_address', 'customer_po',
    # BIR-standard SI summary
    'gross_sales', 'output_vat', 'net_of_vat', 'wht_amount', 'amount_collectible',
    'notes',
]

# Friendly names for the per-field show/hide strip.
FIELD_LABELS = {
    'invoice_no': 'Invoice No.',
    'invoice_date': 'Date',
    'due_date': 'Due Date',
    'terms': 'Terms',
    'customer_name': 'Customer',
    'customer_tin': 'TIN',
    'customer_address': 'Address',
    'customer_po': 'PO No.',
    'gross_sales': 'Total Sales (VAT-incl.)',
    'output_vat': 'VAT',
    'net_of_vat': 'Amount Net of VAT',
    'wht_amount': 'Withholding Tax',
    'amount_collectible': 'Amount Collectible',
    'notes': 'Notes',
}

COLUMN_KEYS = [
    'line_number', 'product', 'quantity',
    'uom', 'unit_price', 'amount',
]

# Header labels for the line-item columns (presentation; keyed by COLUMN_KEYS).
COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'quantity': 'Qty',
    'uom': 'UOM',
    'unit_price': 'Unit Price',
    'amount': 'Amount (₱)',
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

# Date format for the invoice/due dates. key -> strftime. The dropdown labels are
# generated from a sample date so they always match. The JS live-preview mirrors these
# keys (sv_preprinted_designer.js::fmtDate).
DATE_FORMATS = {
    'long':   '%d %B %Y',
    'medium': '%b %d, %Y',
    'us':     '%m/%d/%Y',
    'eu':     '%d/%m/%Y',
    'iso':    '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50   # duplicated field copies cap

# Free-text, LAYOUT-ONLY signature elements (not tied to the invoice record). Editable
# in the designer; the same text prints on every invoice.
TEXT_KEYS = ['preparer', 'checker', 'approver']
TEXT_LABELS = {'preparer': 'Preparer', 'checker': 'Checker', 'approver': 'Approver'}
TEXT_MAXLEN = 200

DEFAULT_SV_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'extras': [],
    'texts': {
        'preparer': {'text': 'Prepared by:', 'x': 60,  'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        'checker':  {'text': 'Checked by:',  'x': 340, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        'approver': {'text': 'Approved by:', 'x': 620, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
    },
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'invoice_no':         {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'invoice_date':       {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'due_date':           {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'terms':              {'x': 520, 'y': 122, 'fontSize': 11, 'bold': False},
        'customer_name':      {'x': 40,  'y': 50,  'fontSize': 12, 'bold': True},
        'customer_tin':       {'x': 40,  'y': 74,  'fontSize': 11, 'bold': False},
        'customer_address':   {'x': 40,  'y': 98,  'fontSize': 11, 'bold': False},
        'customer_po':        {'x': 40,  'y': 122, 'fontSize': 11, 'bold': False},
        'gross_sales':        {'x': 620, 'y': 470, 'fontSize': 10, 'bold': False},
        'output_vat':         {'x': 620, 'y': 494, 'fontSize': 10, 'bold': False},
        'net_of_vat':         {'x': 620, 'y': 518, 'fontSize': 10, 'bold': False},
        'wht_amount':         {'x': 620, 'y': 542, 'fontSize': 10, 'bold': False},
        'amount_collectible': {'x': 620, 'y': 570, 'fontSize': 13, 'bold': True},
        'notes':              {'x': 40,  'y': 600, 'fontSize': 10, 'bold': False},
    },
    # Line items: each column is INDEPENDENTLY positioned (its own x) so it can line
    # up with the pre-printed column boxes; all columns share the band top (y) and
    # rowHeight so rows stay aligned. No header row.
    'lineItems': {
        'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number', 'x': 56,  'visible': True,  'width': 30},
            {'key': 'product',     'x': 92,  'visible': True,  'width': 300},
            {'key': 'quantity',    'x': 430, 'visible': True,  'width': 60},
            {'key': 'uom',         'x': 510, 'visible': True,  'width': 50},
            {'key': 'unit_price',  'x': 580, 'visible': True,  'width': 90},
            {'key': 'amount',      'x': 690, 'visible': True,  'width': 100},
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
        'x': _clamp(raw.get('x'), 0, CANVAS_W, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
        'hidden': bool(raw.get('hidden', default.get('hidden', False))),
    }


def _clean_columns(raw):
    raw = raw if isinstance(raw, list) else []
    by_key = {c.get('key'): c for c in raw if isinstance(c, dict) and c.get('key') in COLUMN_KEYS}
    defaults = {c['key']: c for c in DEFAULT_SV_PREPRINTED_LAYOUT['lineItems']['columns']}
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
            'x': _clamp(e.get('x'), 0, CANVAS_W, 0),
            'y': _clamp(e.get('y'), 0, CANVAS_H, 0),
            'fontSize': _clamp(e.get('fontSize'), FONT_MIN, FONT_MAX, 11),
            'bold': bool(e.get('bold', False)),
        })
    return out


def _clean_texts(raw):
    """Layout-only signature texts (preparer/checker/approver)."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_SV_PREPRINTED_LAYOUT['texts']
    out = {}
    for k in TEXT_KEYS:
        src = raw.get(k) if isinstance(raw.get(k), dict) else {}
        dk = d[k]
        text = src.get('text', dk['text'])
        text = str(text)[:TEXT_MAXLEN] if text is not None else dk['text']
        out[k] = {
            'text': text,
            'x': _clamp(src.get('x'), 0, CANVAS_W, dk['x']),
            'y': _clamp(src.get('y'), 0, CANVAS_H, dk['y']),
            'fontSize': _clamp(src.get('fontSize'), FONT_MIN, FONT_MAX, dk['fontSize']),
            'bold': bool(src.get('bold', dk['bold'])),
            'hidden': bool(src.get('hidden', dk['hidden'])),
        }
    return out


def sanitize_layout(raw):
    """Return a fully-populated, validated layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_SV_PREPRINTED_LAYOUT
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
            'texts': _clean_texts(raw.get('texts')),
            'page': page, 'fields': fields, 'lineItems': line_items}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)


def save_layout(raw, username, branch_id=None):
    """Sanitize, persist (per branch), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='sales_invoices', action='update', record_id=None,
              record_identifier='sv_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'Pre-printed layout updated (branch {branch_id})')
    return clean
