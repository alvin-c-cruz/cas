"""Shared core for the pre-printed stationery print designer.

Eight modules (Sales Order, Sales Invoice, Accounts Payable, Cash Disbursements,
Cash Receipts, Journal Entries, Delivery Receipts, Payroll) each carry their own
near-identical `preprinted_layout.py` -- same canvas/font/paper constants, same
sanitizer shape, same get/save-per-branch persistence, differing only in the
document's own setting key, field list and defaults. This module is that shared
core, factored out so a NINTH/TENTH/ELEVENTH clone (Purchase Order, Purchase
Requisition, Receiving Report) is a thin declaration instead of another copy.

The whole layout is one JSON value in an app_settings row, per branch. Everything
is sanitized on read AND write against a document's own defaults, so stored or
POSTed JSON can never inject unknown keys, out-of-range numbers, or an unlisted
font, and a layout saved before a new field existed still renders that field at
its default.

Do NOT import from any existing module's `preprinted_layout.py` here, and do not
import this module from one of them -- the eight existing clones stay untouched
and independently changeable; this base stands alone.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

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

# Date format for document header dates. key -> strftime. The dropdown labels are
# generated from a sample date so they always match.
DATE_FORMATS = {
    'long':   '%d %B %Y',
    'medium': '%b %d, %Y',
    'us':     '%m/%d/%Y',
    'eu':     '%d/%m/%Y',
    'iso':    '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50   # duplicated field copies cap

# Free-text, LAYOUT-ONLY signature elements (not tied to any document record).
# Shared across every document -- unlike FIELD_KEYS/defaults these do not vary
# per document, so they live here as constants rather than being redeclared by
# each of the three thin P2P modules.
TEXT_KEYS = ['preparer', 'checker', 'approver']
TEXT_LABELS = {'preparer': 'Preparer', 'checker': 'Checker', 'approver': 'Approver'}
TEXT_MAXLEN = 200


def _clamp(value, lo, hi, fallback):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, n))


def _clean_box(raw, default):
    """One field's position/style. Includes 'w' (width) -- unlike the eight
    existing per-document clones, a P2P document's fields carry their own width
    (used for text wrapping/alignment on the print), so it is validated here."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        'x': _clamp(raw.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'w': _clamp(raw.get('w'), WIDTH_MIN, WIDTH_MAX, default.get('w', WIDTH_MIN)),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
        'hidden': bool(raw.get('hidden', default.get('hidden', False))),
    }


def _clean_line_items(raw_li, default_li):
    """Line-item band position/style. `columns` is passed through opaquely
    (dict or list, whatever shape the document chooses) -- unlike the eight
    existing clones, the base has no shared COLUMN_KEYS to validate against
    (each P2P document's own line-item columns differ and are that document's
    own concern), so only the shared band bounds (y/rowHeight/fontSize/bold)
    are sanitized here."""
    raw_li = raw_li if isinstance(raw_li, dict) else {}
    columns = raw_li.get('columns')
    if not isinstance(columns, (dict, list)):
        columns = default_li.get('columns')
    return {
        'y': _clamp(raw_li.get('y'), 0, CANVAS_H, default_li['y']),
        'rowHeight': _clamp(raw_li.get('rowHeight'), ROW_MIN, ROW_MAX, default_li['rowHeight']),
        'fontSize': _clamp(raw_li.get('fontSize'), FONT_MIN, FONT_MAX, default_li['fontSize']),
        'bold': bool(raw_li.get('bold', default_li['bold'])),
        'columns': columns,
    }


def _clean_extras(raw, field_keys):
    """Duplicated field copies: each references a field_keys key + its own position/style."""
    raw = raw if isinstance(raw, list) else []
    out = []
    for e in raw[:MAX_EXTRAS]:
        if not isinstance(e, dict) or e.get('key') not in field_keys:
            continue
        out.append({
            'key': e['key'],
            'x': _clamp(e.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, 0),
            'y': _clamp(e.get('y'), 0, CANVAS_H, 0),
            'fontSize': _clamp(e.get('fontSize'), FONT_MIN, FONT_MAX, 11),
            'bold': bool(e.get('bold', False)),
        })
    return out


def _texts_defaults(default_layout):
    """Normalize `default_layout['texts']` into the box-list shape `clean_texts`
    expects (`[{id, text, x, y, fontSize, bold, hidden}, ...]`).

    A document's own defaults may already provide that full shape, or -- the
    common case for these documents, which have no per-signatory positioning of
    their own -- a bare `{id: text}` map. Either is accepted; a plain string
    value (including '') survives into the box's 'text' unchanged rather than
    being replaced by a placeholder, so a default of '' stays '' on both an
    empty-input sanitize and a defaults-echoed-back sanitize."""
    dt = default_layout.get('texts')
    if isinstance(dt, list):
        return dt
    dt = dt if isinstance(dt, dict) else {}
    return [
        {
            'id': k,
            'text': str(dt.get(k) or ''),
            'x': SAFE_MARGIN,
            'y': CANVAS_H - SAFE_MARGIN,
            'fontSize': 10,
            'bold': False,
            'hidden': False,
        }
        for k in TEXT_KEYS
    ]


def build_layout_api(setting_key, field_keys, default_layout, audit_module, audit_identifier):
    """Return (sanitize_layout, get_layout, save_layout) bound to one document type.

    Everything these three do is identical across documents EXCEPT the setting
    key, the field list and the defaults -- which is why the eight existing
    per-module copies differ by only ~76 lines once their document names are
    normalised. A module declares its own identity and inherits the rest.
    """

    def sanitize_layout(raw):
        """Return a fully-populated, validated layout built from `raw` over the defaults."""
        raw = raw if isinstance(raw, dict) else {}
        d = default_layout
        paper = raw.get('paper') if raw.get('paper') in ALLOWED_PAPERS else d['paper']
        date_fmt = raw.get('dateFormat') if raw.get('dateFormat') in ALLOWED_DATE_FORMATS else d['dateFormat']
        font = (raw.get('page') or {}).get('fontFamily')
        page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
        raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
        fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in field_keys}
        line_items = _clean_line_items(raw.get('lineItems'), d['lineItems'])
        extras = _clean_extras(raw.get('extras'), field_keys)
        texts = clean_texts(raw.get('texts'), _texts_defaults(d))
        return {
            'paper': paper,
            'dateFormat': date_fmt,
            'page': page,
            'fields': fields,
            'lineItems': line_items,
            'extras': extras,
            'texts': texts,
        }

    def _layout_key(branch_id):
        """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
        return f'{setting_key}:{branch_id}' if branch_id is not None else setting_key

    def get_layout(branch_id=None):
        """Current sanitized layout for a branch (defaults if unset or corrupt)."""
        stored = AppSettings.get_setting(_layout_key(branch_id))
        if not stored:
            return sanitize_layout(copy.deepcopy(default_layout))
        try:
            return sanitize_layout(json.loads(stored))
        except (ValueError, TypeError):
            return sanitize_layout(copy.deepcopy(default_layout))

    def save_layout(raw, username, branch_id=None):
        """Sanitize, persist (per branch), audit, and return the clean layout."""
        clean = sanitize_layout(raw)
        key = _layout_key(branch_id)
        old = AppSettings.get_setting(key)
        AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
        log_audit(module=audit_module, action='update', record_id=None,
                  record_identifier=audit_identifier,
                  old_values={'layout': old, 'branch_id': branch_id},
                  new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
                  notes=f'Pre-printed layout updated (branch {branch_id})')
        return clean

    return sanitize_layout, get_layout, save_layout
