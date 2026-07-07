"""Layout model for the Cash Receipt Voucher pre-printed print designer.

Clone of the Sales Invoice pre-printed layout (SI-P-71), adapted to the CRV
format. The whole layout is one JSON value in an app_settings row, sanitized on
read AND write against these defaults, so stored or POSTed JSON can never inject
unknown keys, out-of-range numbers, or an unlisted font, and a layout saved
before a new field/column existed still renders it at its default.

Deliberately independent of the SI module (APV/CDV have different formats — no
shared engine); the two files may diverge freely.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'crv_preprinted_layout'

# Dot-matrix continuous-form stock: 9.5in x 10.5in @96dpi (CSS px) so on-screen
# drags map 1:1 to the printed form.
CANVAS_W = 912      # 9.5in  @96dpi
CANVAS_H = 1008     # 10.5in @96dpi
SAFE_MARGIN = 48   # printable inset (tractor-feed margin); element x is clamped inside it
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 912
ROW_MIN, ROW_MAX = 8, 80

# Grouped font picker; monospace faces rasterize cleanest on dot-matrix printers
# (browsers print in graphics/raster mode, so the CSS font DOES reach output), so
# they lead. Each entry ends in a generic family to cap silent fallback.
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
ALLOWED_FONTS = [f for _label, _fonts in FONT_GROUPS for f in _fonts]

FIELD_KEYS = [
    'crv_no', 'crv_date',
    'customer_name', 'customer_tin', 'customer_address',
    'payment_method', 'check_no', 'check_date', 'check_bank',
    # BIR-standard CRV summary
    'ar_applied', 'direct_revenue', 'output_vat', 'wht_amount', 'net_cash_received',
    'notes',
]

FIELD_LABELS = {
    'crv_no': 'CRV No.',
    'crv_date': 'Date',
    'customer_name': 'Payer',
    'customer_tin': 'TIN',
    'customer_address': 'Address',
    'payment_method': 'Payment',
    'check_no': 'Check No.',
    'check_date': 'Check Date',
    'check_bank': 'Bank',
    'ar_applied': 'AR Applied',
    'direct_revenue': 'Direct Revenue',
    'output_vat': 'VAT',
    'wht_amount': 'Withholding Tax',
    'net_cash_received': 'Net Cash Received',
    'notes': 'Notes',
}

# Line-item band = the AR-collection lines (a collection receipt's body). Direct
# revenue product lines are out of scope for v1.
COLUMN_KEYS = [
    'line_number', 'invoice_no', 'invoice_date', 'original_balance', 'amount_applied',
]

COLUMN_LABELS = {
    'line_number': '#',
    'invoice_no': 'Invoice No.',
    'invoice_date': 'Inv. Date',
    'original_balance': 'Balance',
    'amount_applied': 'Amount Paid',
}

ALLOWED_PAPERS = ('continuous', 'letter')

PAPER_SIZES = {
    'continuous': {'w': 912, 'h': 1008, 'css': '9.5in 10.5in'},
    'letter':     {'w': 816, 'h': 1056, 'css': '8.5in 11in'},
}
PAPER_LABELS = {
    'continuous': '9.5 x 10.5 continuous paper',
    'letter':     'Letter 8.5 x 11',
}

DATE_FORMATS = {
    'long':   '%d %B %Y',
    'medium': '%b %d, %Y',
    'us':     '%m/%d/%Y',
    'eu':     '%d/%m/%Y',
    'iso':    '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50

# Free-text, LAYOUT-ONLY signature elements (not tied to the CRV record).
TEXT_KEYS = ['prepared_by', 'received_by', 'approved_by']
TEXT_LABELS = {'prepared_by': 'Prepared by', 'received_by': 'Received by',
               'approved_by': 'Approved by'}
TEXT_MAXLEN = 200

DEFAULT_CRV_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'extras': [],
    'texts': [
        {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60,  'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'received_by', 'text': 'Received by:', 'x': 340, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'approved_by', 'text': 'Approved by:', 'x': 620, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
    ],
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'crv_no':            {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'crv_date':          {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'payment_method':    {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'check_no':          {'x': 520, 'y': 122, 'fontSize': 11, 'bold': False},
        'check_date':        {'x': 520, 'y': 146, 'fontSize': 11, 'bold': False},
        'check_bank':        {'x': 520, 'y': 170, 'fontSize': 11, 'bold': False},
        'customer_name':     {'x': 60,  'y': 50,  'fontSize': 12, 'bold': True},
        'customer_tin':      {'x': 60,  'y': 74,  'fontSize': 11, 'bold': False},
        'customer_address':  {'x': 60,  'y': 98,  'fontSize': 11, 'bold': False},
        'ar_applied':        {'x': 620, 'y': 470, 'fontSize': 10, 'bold': False},
        'direct_revenue':    {'x': 620, 'y': 494, 'fontSize': 10, 'bold': False},
        'output_vat':        {'x': 620, 'y': 518, 'fontSize': 10, 'bold': False},
        'wht_amount':        {'x': 620, 'y': 542, 'fontSize': 10, 'bold': False},
        'net_cash_received': {'x': 620, 'y': 570, 'fontSize': 13, 'bold': True},
        'notes':             {'x': 60,  'y': 600, 'fontSize': 10, 'bold': False},
    },
    # AR-collection lines: each column INDEPENDENTLY positioned (own x); all share
    # the band top (y) + rowHeight. No header row.
    'lineItems': {
        'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number',      'x': 56,  'visible': True, 'width': 30},
            {'key': 'invoice_no',       'x': 92,  'visible': True, 'width': 130},
            {'key': 'invoice_date',     'x': 240, 'visible': True, 'width': 100},
            {'key': 'original_balance', 'x': 450, 'visible': True, 'width': 110},
            {'key': 'amount_applied',   'x': 580, 'visible': True, 'width': 110},
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
    defaults = {c['key']: c for c in DEFAULT_CRV_PREPRINTED_LAYOUT['lineItems']['columns']}
    ordered_keys = [c['key'] for c in raw
                    if isinstance(c, dict) and c.get('key') in COLUMN_KEYS]
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
    d = DEFAULT_CRV_PREPRINTED_LAYOUT
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
            'texts': clean_texts(raw.get('texts'), DEFAULT_CRV_PREPRINTED_LAYOUT['texts']),
            'page': page, 'fields': fields, 'lineItems': line_items}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_CRV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_CRV_PREPRINTED_LAYOUT)


def save_layout(raw, username, branch_id=None):
    """Sanitize, persist (per branch), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='cash_receipts', action='update', record_id=None,
              record_identifier='crv_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'CRV pre-printed layout updated (branch {branch_id})')
    return clean
