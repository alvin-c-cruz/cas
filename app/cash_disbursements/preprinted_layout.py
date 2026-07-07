"""Layout model for the Cash Disbursement Voucher pre-printed print designer.

Clone of the APV pre-printed layout (line band + JE face), adapted to the CDV
format. The whole layout is one JSON value in an app_settings row, sanitized on
read AND write against these defaults. Branch-scoped from birth
(key `cd_preprinted_layout:<branch_id>`).

Per the CDV voucher design (user 2026-07-07): the line band = Section B (Direct
Expenses) only; Section A (AP Bills Paid) and the SUMMARY block are NOT rendered,
and the JE face carries no TOTAL row (that lives in the template).

Deliberately independent of the SI/CRV/APV modules (each document has its own
format — no shared engine); the files may diverge freely.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'cd_preprinted_layout'

# Dot-matrix continuous-form stock: 9.5in x 10.5in @96dpi (CSS px).
CANVAS_W = 912
CANVAS_H = 1008
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 912
ROW_MIN, ROW_MAX = 8, 80

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
    'cdv_no', 'cdv_date', 'payment_method',
    'check_no', 'check_date', 'check_bank', 'cash_account',
    'vendor_name', 'vendor_tin',
    'notes',
]

FIELD_LABELS = {
    'cdv_no': 'CDV No.',
    'cdv_date': 'Date',
    'payment_method': 'Payment',
    'check_no': 'Check No.',
    'check_date': 'Check Date',
    'check_bank': 'Bank',
    'cash_account': 'Cash/Bank Acct',
    'vendor_name': 'Pay To',
    'vendor_tin': 'TIN',
    'notes': 'Notes',
}

# Line band = Section B (Direct Expenses). Section A (AP Bills Paid) is NOT a band.
COLUMN_KEYS = [
    'line_number', 'product', 'description', 'qty', 'uom', 'unit_price',
    'account_title', 'amount',
]

COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'description': 'Description',
    'qty': 'Qty',
    'uom': 'UOM',
    'unit_price': 'Unit Price',
    'account_title': 'Account Title',
    'amount': 'Amount',
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

TEXT_KEYS = ['prepared_by', 'checked_by', 'approved_by']

JE_MODES = ('combined', 'separated')

DEFAULT_CDV_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'extras': [],
    'texts': [
        {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60,  'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'checked_by',  'text': 'Checked by:',  'x': 340, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'approved_by', 'text': 'Approved by:', 'x': 620, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
    ],
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    'fields': {
        'cdv_no':         {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'cdv_date':       {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'payment_method': {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'check_no':       {'x': 520, 'y': 122, 'fontSize': 11, 'bold': False},
        'check_date':     {'x': 520, 'y': 146, 'fontSize': 11, 'bold': False},
        'check_bank':     {'x': 520, 'y': 170, 'fontSize': 11, 'bold': False},
        'vendor_name':    {'x': 40,  'y': 50,  'fontSize': 12, 'bold': True},
        'vendor_tin':     {'x': 40,  'y': 74,  'fontSize': 11, 'bold': False},
        'cash_account':   {'x': 40,  'y': 98,  'fontSize': 11, 'bold': False},
        'notes':          {'x': 40,  'y': 600, 'fontSize': 10, 'bold': False},
    },
    # Journal-entry face: mode combined (one grid) or separated (a debit band + a
    # credit band). All three bands carry a position so switching mode never loses
    # the other mode's layout. NO total row (rendered in the template).
    'journalEntry': {
        'mode': 'combined',
        'fontSize': 9,
        'rowHeight': 16,
        'combined': {'x': 40,  'y': 360, 'width': 460},
        'debit':    {'x': 40,  'y': 360, 'width': 300},
        'credit':   {'x': 470, 'y': 360, 'width': 300},
    },
    # Section B (Direct Expenses) lines: each column INDEPENDENTLY positioned (own x);
    # all share the band top (y) + rowHeight. No header row.
    'lineItems': {
        'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number',   'x': 40,  'visible': True, 'width': 30},
            {'key': 'product',       'x': 76,  'visible': True, 'width': 120},
            {'key': 'description',   'x': 200, 'visible': True, 'width': 210},
            {'key': 'qty',           'x': 420, 'visible': True, 'width': 60},
            {'key': 'uom',           'x': 486, 'visible': True, 'width': 50},
            {'key': 'unit_price',    'x': 542, 'visible': True, 'width': 90},
            {'key': 'account_title', 'x': 638, 'visible': True, 'width': 160},
            {'key': 'amount',        'x': 804, 'visible': True, 'width': 100},
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
    defaults = {c['key']: c for c in DEFAULT_CDV_PREPRINTED_LAYOUT['lineItems']['columns']}
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


def _clean_je(raw):
    """The CDV journal-entry face: mode + three positioned bands (layout only)."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_CDV_PREPRINTED_LAYOUT['journalEntry']
    mode = raw.get('mode') if raw.get('mode') in JE_MODES else d['mode']

    def band(key):
        b = raw.get(key) if isinstance(raw.get(key), dict) else {}
        db_ = d[key]
        return {
            'x': _clamp(b.get('x'), 0, CANVAS_W, db_['x']),
            'y': _clamp(b.get('y'), 0, CANVAS_H, db_['y']),
            'width': _clamp(b.get('width'), WIDTH_MIN, WIDTH_MAX, db_['width']),
        }

    return {
        'mode': mode,
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, d['fontSize']),
        'rowHeight': _clamp(raw.get('rowHeight'), ROW_MIN, ROW_MAX, d['rowHeight']),
        'combined': band('combined'),
        'debit': band('debit'),
        'credit': band('credit'),
    }


def sanitize_layout(raw):
    """Return a fully-populated, validated layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_CDV_PREPRINTED_LAYOUT
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
            'texts': clean_texts(raw.get('texts'), DEFAULT_CDV_PREPRINTED_LAYOUT['texts']),
            'page': page, 'fields': fields, 'lineItems': line_items,
            'journalEntry': _clean_je(raw.get('journalEntry'))}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_CDV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_CDV_PREPRINTED_LAYOUT)


def save_layout(raw, username, branch_id=None):
    """Sanitize, persist (per branch), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='cash_disbursements', action='update', record_id=None,
              record_identifier='cdv_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'CDV pre-printed layout updated (branch {branch_id})')
    return clean
