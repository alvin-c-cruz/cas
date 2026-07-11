"""Layout model for the Journal Voucher pre-printed print designer.

Faithful per-doc clone of the APV pre-printed layout, adapted to the JV format.
The whole layout is one JSON value in an app_settings row, sanitized on read AND
write against these defaults, so stored or POSTed JSON can never inject unknown
keys, out-of-range numbers, or an unlisted font, and a layout saved before a new
field/column existed still renders it at its default.

Unlike APV this has NO `journalEntry` face block: a Journal Voucher's lines ARE
the entry, so they are drawn by the `lineItems` band (columns: line# / code /
account title / debit / credit). Branch-scoped from birth
(key `jv_preprinted_layout:<branch_id>`).
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'jv_preprinted_layout'

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

FIELD_KEYS = ['jv_no', 'jv_date', 'entry_type', 'particulars', 'total_debit', 'total_credit']

FIELD_LABELS = {
    'jv_no': 'JV No.',
    'jv_date': 'Date',
    'entry_type': 'Entry Type',
    'particulars': 'Particulars',
    'total_debit': 'Total Debit',
    'total_credit': 'Total Credit',
}

# Line band = the journal-voucher entry lines themselves.
COLUMN_KEYS = ['line_number', 'account_code', 'account_title', 'debit', 'credit']

COLUMN_LABELS = {
    'line_number': '#',
    'account_code': 'Code',
    'account_title': 'Account Title',
    'debit': 'Debit',
    'credit': 'Credit',
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

# Free-text, LAYOUT-ONLY signature elements (not tied to the JV record).
TEXT_KEYS = ['prepared_by', 'checked_by', 'approved_by']
TEXT_LABELS = {'prepared_by': 'Prepared by', 'checked_by': 'Checked by',
               'approved_by': 'Approved by'}
TEXT_MAXLEN = 200

DEFAULT_JV_PREPRINTED_LAYOUT = {
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
        'jv_no':        {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'jv_date':      {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        'entry_type':   {'x': 520, 'y': 98,  'fontSize': 11, 'bold': False},
        'particulars':  {'x': 60,  'y': 50,  'fontSize': 11, 'bold': False},
        'total_debit':  {'x': 560, 'y': 560, 'fontSize': 11, 'bold': True},
        'total_credit': {'x': 700, 'y': 560, 'fontSize': 11, 'bold': True},
    },
    # Entry lines: each column INDEPENDENTLY positioned (own x); all share the band
    # top (y) + rowHeight. No header row. The JV lines ARE the accounting entry.
    'lineItems': {
        'y': 300, 'rowHeight': 20, 'fontSize': 10, 'bold': False,
        'columns': [
            {'key': 'line_number',   'x': 40,  'visible': True, 'width': 30},
            {'key': 'account_code',  'x': 76,  'visible': True, 'width': 90},
            {'key': 'account_title', 'x': 176, 'visible': True, 'width': 300},
            {'key': 'debit',         'x': 560, 'visible': True, 'width': 120},
            {'key': 'credit',        'x': 700, 'visible': True, 'width': 120},
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
    defaults = {c['key']: c for c in DEFAULT_JV_PREPRINTED_LAYOUT['lineItems']['columns']}
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
    d = DEFAULT_JV_PREPRINTED_LAYOUT
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
            'texts': clean_texts(raw.get('texts'), DEFAULT_JV_PREPRINTED_LAYOUT['texts']),
            'page': page, 'fields': fields, 'lineItems': line_items}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_JV_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_JV_PREPRINTED_LAYOUT)


def save_layout(raw, username, branch_id=None):
    """Sanitize, persist (per branch), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='journal_entries', action='update', record_id=None,
              record_identifier='jv_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'JV pre-printed layout updated (branch {branch_id})')
    return clean
