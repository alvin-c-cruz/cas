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

CANVAS_W = 794      # A4 @96dpi
CANVAS_H = 1123
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 794

ALLOWED_FONTS = [
    'Arial, sans-serif',
    'Helvetica, Arial, sans-serif',
    '"Times New Roman", Times, serif',
    'Georgia, serif',
    '"Courier New", Courier, monospace',
    'Verdana, Geneva, sans-serif',
]

FIELD_KEYS = [
    'invoice_no', 'invoice_date', 'due_date', 'terms',
    'customer_name', 'customer_tin', 'customer_address', 'customer_po',
    'amount_collectible', 'notes',
]

COLUMN_KEYS = [
    'line_number', 'description', 'product', 'quantity',
    'uom', 'unit_price', 'amount',
]

# Header labels for the line-item columns (presentation; keyed by COLUMN_KEYS).
COLUMN_LABELS = {
    'line_number': '#',
    'description': 'Description / Particulars',
    'product': 'Product',
    'quantity': 'Qty',
    'uom': 'UOM',
    'unit_price': 'Unit Price',
    'amount': 'Amount (₱)',
}

DEFAULT_SV_PREPRINTED_LAYOUT = {
    'page': {'fontFamily': 'Arial, sans-serif'},
    'fields': {
        'invoice_no':         {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'invoice_date':       {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'due_date':           {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'terms':              {'x': 520, 'y': 122, 'fontSize': 11, 'bold': False},
        'customer_name':      {'x': 40,  'y': 50,  'fontSize': 12, 'bold': True},
        'customer_tin':       {'x': 40,  'y': 74,  'fontSize': 11, 'bold': False},
        'customer_address':   {'x': 40,  'y': 98,  'fontSize': 11, 'bold': False},
        'customer_po':        {'x': 40,  'y': 122, 'fontSize': 11, 'bold': False},
        'amount_collectible': {'x': 520, 'y': 560, 'fontSize': 13, 'bold': True},
        'notes':              {'x': 40,  'y': 600, 'fontSize': 10, 'bold': False},
    },
    'lineItems': {
        'x': 40, 'y': 190, 'width': 714, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number', 'visible': True,  'width': 30},
            {'key': 'description', 'visible': True,  'width': 300},
            {'key': 'product',     'visible': False, 'width': 120},
            {'key': 'quantity',    'visible': True,  'width': 70},
            {'key': 'uom',         'visible': True,  'width': 60},
            {'key': 'unit_price',  'visible': True,  'width': 90},
            {'key': 'amount',      'visible': True,  'width': 100},
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
            'visible': bool(src.get('visible', d['visible'])),
            'width': _clamp(src.get('width'), WIDTH_MIN, WIDTH_MAX, d['width']),
        })
    return out


def sanitize_layout(raw):
    """Return a fully-populated, validated layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_SV_PREPRINTED_LAYOUT
    font = (raw.get('page') or {}).get('fontFamily')
    page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS}
    raw_li = raw.get('lineItems') if isinstance(raw.get('lineItems'), dict) else {}
    dli = d['lineItems']
    line_items = {
        'x': _clamp(raw_li.get('x'), 0, CANVAS_W, dli['x']),
        'y': _clamp(raw_li.get('y'), 0, CANVAS_H, dli['y']),
        'width': _clamp(raw_li.get('width'), WIDTH_MIN, WIDTH_MAX, dli['width']),
        'fontSize': _clamp(raw_li.get('fontSize'), FONT_MIN, FONT_MAX, dli['fontSize']),
        'bold': bool(raw_li.get('bold', dli['bold'])),
        'columns': _clean_columns(raw_li.get('columns')),
    }
    return {'page': page, 'fields': fields, 'lineItems': line_items}


def get_layout():
    """Current sanitized layout (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(LAYOUT_SETTING_KEY)
    if not stored:
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_SV_PREPRINTED_LAYOUT)


def save_layout(raw, username):
    """Sanitize, persist, audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    old = AppSettings.get_setting(LAYOUT_SETTING_KEY)
    AppSettings.set_setting(LAYOUT_SETTING_KEY, json.dumps(clean), updated_by=username)
    log_audit(module='sales_invoices', action='update', record_id=None,
              record_identifier='sv_preprinted_layout',
              old_values={'layout': old}, new_values={'layout': json.dumps(clean)},
              notes='Pre-printed layout updated')
    return clean
