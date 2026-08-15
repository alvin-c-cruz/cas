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
MAX_COLUMNS = 40  # line-item column cap -- the total-size ceiling on a stored layout

# Free-text, LAYOUT-ONLY signature elements (not tied to any document record).
# Shared across every document -- unlike FIELD_KEYS/defaults these do not vary
# per document, so they live here as constants rather than being redeclared by
# each of the three thin P2P modules.
TEXT_KEYS = ['preparer', 'checker', 'approver']
TEXT_LABELS = {'preparer': 'Preparer', 'checker': 'Checker', 'approver': 'Approver'}
TEXT_MAXLEN = 200

# Default signatory positions, in TEXT_KEYS order -- the three signature blocks sit
# side by side across the foot of the form. These are the owner-approved mockup's
# positions (docs/mockups/2026-08-15-p2p-preprinted-designer.html) and match the
# existing SO layout's defaults; a single shared point would stack all three labels
# on top of each other on a new branch's first print.
TEXT_DEFAULT_XS = [60, 340, 620]
TEXT_DEFAULT_Y = 720
TEXT_DEFAULT_FONT_SIZE = 10


def _clamp(value, lo, hi, fallback):
    """Coerce `value` into lo..hi, falling back to `fallback` on anything unusable.

    OverflowError is caught alongside TypeError/ValueError because Python's JSON
    reader parses `1e999` (and the bare `Infinity` token) into a float infinity,
    which `round()` refuses to convert to an int. That is valid JSON reaching a
    sanitiser that must never raise -- see `sanitize_layout`.
    """
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return max(lo, min(hi, n))


def _clean_box(raw, default):
    """One field's position/style. Includes 'w' (width) -- unlike the eight
    existing per-document clones, a P2P document's fields carry their own width
    (used for text wrapping/alignment on the print), so it is validated here.

    `default` MUST carry an explicit 'w' (checked once, at build_layout_api time):
    a silent WIDTH_MIN fallback would print every field of a document clipped to
    10px, a defect that only shows up on physical stationery."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        'x': _clamp(raw.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'w': _clamp(raw.get('w'), WIDTH_MIN, WIDTH_MAX, default['w']),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
        'hidden': bool(raw.get('hidden', default.get('hidden', False))),
    }


def _clean_columns(raw, default_columns):
    """Line-item columns, validated against the document's OWN default columns.

    Generic lift of the per-module `_clean_columns` (see
    `app/sales_orders/preprinted_layout.py`): the base has no shared COLUMN_KEYS,
    but it does not need one -- the allowed key set, the canonical ORDER and the
    per-key defaults all arrive inside `default_columns`, so the allow-list is
    derived from the defaults.

    - a key that is not a plain string is dropped, like any other unknown key.
      This is load-bearing, not defensive tidiness: `defaults` is a DICT, so
      `key in defaults` HASHES the key, and a stored/POSTed
      `{"columns": [{"key": [1]}]}` -- valid JSON -- would raise
      `TypeError: unhashable type: 'list'` straight out of the sanitiser.
      `get_layout` swallows that, but `save_layout` has no guard, so an
      authenticated POST would 500. `_clean_extras` tests membership against a
      LIST (`==`, never hashes) and is immune by construction; this function is
      made to match it,
    - other unknown keys are dropped too (a stored layout can never inject a
      column),
    - x/width are clamped, `visible` is coerced to bool. A column's x is clamped
      to SAFE_MARGIN..CANVAS_W - SAFE_MARGIN, i.e. EXACTLY like a field's
      (`_clean_box`). It used to clamp to the bare canvas (0..CANVAS_W), which
      let a user drag a column onto the tractor-feed perforations and have the
      server persist it there, while a field dragged to the same spot was pulled
      back to the margin. That asymmetry was removed deliberately on 2026-08-15
      (owner decision: tighten the server, not loosen the client, so what is
      dragged is what is stored). The declaration validator carries the same
      bound, so a declared column may not sit in the margin either,
    - first-seen input order is kept, then ANY known column the input omitted is
      appended at its default -- the column-level forward-compat case: a release
      that adds a column must still print it for a client whose stored JSON
      predates it,
    - a key repeated in the input resolves to its FIRST occurrence, for BOTH its
      values and its position. Values and ordering are built in one pass over one
      dict so the two can never disagree (they previously did: last-wins values
      at a first-wins position),
    - the result is ALWAYS a list (a stored/declared dict iterates as bare string
      keys in Jinja and silently renders `left:px;width:px`), capped at
      MAX_COLUMNS, and always built from FRESH dicts so a caller mutating the
      returned layout can never reach the module-level defaults.

    A document with no line-item columns declares anything non-list (or omits the
    key) and gets `[]`.
    """
    default_columns = default_columns if isinstance(default_columns, list) else []
    defaults = {c['key']: c for c in default_columns
                if isinstance(c, dict) and isinstance(c.get('key'), str)}
    column_keys = list(defaults)
    raw = raw[:MAX_COLUMNS] if isinstance(raw, list) else []
    by_key = {}
    for c in raw:
        if not isinstance(c, dict):
            continue
        k = c.get('key')
        if isinstance(k, str) and k in defaults and k not in by_key:
            by_key[k] = c
    # first-seen input order, then any known column the input omitted
    order = list(by_key) + [k for k in column_keys if k not in by_key]
    out = []
    for k in order[:MAX_COLUMNS]:
        src = by_key.get(k) or {}
        d = defaults[k]
        out.append({
            'key': k,
            'x': _clamp(src.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, d['x']),
            'visible': bool(src.get('visible', d.get('visible', True))),
            'width': _clamp(src.get('width'), WIDTH_MIN, WIDTH_MAX, d['width']),
        })
    return out


def _clean_line_items(raw_li, default_li):
    """Line-item band position/style plus its validated `columns` list."""
    raw_li = raw_li if isinstance(raw_li, dict) else {}
    return {
        'y': _clamp(raw_li.get('y'), 0, CANVAS_H, default_li['y']),
        'rowHeight': _clamp(raw_li.get('rowHeight'), ROW_MIN, ROW_MAX, default_li['rowHeight']),
        'fontSize': _clamp(raw_li.get('fontSize'), FONT_MIN, FONT_MAX, default_li['fontSize']),
        'bold': bool(raw_li.get('bold', default_li['bold'])),
        'columns': _clean_columns(raw_li.get('columns'), default_li.get('columns')),
    }


def _clean_extras(raw, field_keys):
    """Duplicated field copies: each references a field_keys key + its own position/style.

    The `isinstance(..., str)` guard mirrors `_clean_columns`. Membership here is
    tested against a LIST, so an unhashable key would NOT raise -- but the two
    siblings sanitise the same user-supplied `key` slot and must not differ in
    which payloads they accept.
    """
    raw = raw if isinstance(raw, list) else []
    out = []
    for e in raw[:MAX_EXTRAS]:
        if not isinstance(e, dict) or not isinstance(e.get('key'), str) \
                or e['key'] not in field_keys:
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
    empty-input sanitize and a defaults-echoed-back sanitize.

    The bare-map form gets the three side-by-side signatory positions from
    TEXT_DEFAULT_XS / TEXT_DEFAULT_Y -- one shared point would stack preparer,
    checker and approver on top of each other."""
    dt = default_layout.get('texts')
    if isinstance(dt, list):
        return dt
    dt = dt if isinstance(dt, dict) else {}
    return [
        {
            'id': k,
            'text': str(dt.get(k) or ''),
            'x': TEXT_DEFAULT_XS[i] if i < len(TEXT_DEFAULT_XS) else TEXT_DEFAULT_XS[-1],
            'y': TEXT_DEFAULT_Y,
            'fontSize': TEXT_DEFAULT_FONT_SIZE,
            'bold': False,
            'hidden': False,
        }
        for i, k in enumerate(TEXT_KEYS)
    ]


def _check_num(box, prop, lo, hi, where):
    """Declared numeric prop must be PRESENT, numeric, and already in range.

    Presence alone is not enough. `_clamp`'s fallback arm returns the declared
    value untouched when the stored value is unparseable, and that arm is not
    itself clamped -- so a declared `'w': 'wide'` reaches the template as
    `width:widepx`, and `'x': None` as `left:Nonepx`. A declared `'x': 99999`
    survives every clamp for the same reason. Those are the exact defect this
    validator exists to close, one level down.

    `bool` is excluded explicitly: `isinstance(True, int)` is True in Python, so
    a declared `'x': True` would otherwise pass a bare numeric check and print at
    x=1.
    """
    if prop not in box:
        raise ValueError(f'{where} is missing {prop!r}')
    v = box[prop]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f'{where}[{prop!r}] is {v!r}; must be a number in {lo}..{hi}')
    if not lo <= v <= hi:   # also rejects nan and +/-inf
        raise ValueError(f'{where}[{prop!r}] is {v!r}; must be in {lo}..{hi}')


def _check_bool(box, prop, where, required=True):
    """Declared bool prop must be PRESENT (unless optional) and an actual bool."""
    if prop not in box:
        if required:
            raise ValueError(f'{where} is missing {prop!r}')
        return
    if not isinstance(box[prop], bool):
        raise ValueError(f'{where}[{prop!r}] is {box[prop]!r}; must be a bool')


def _validate_default_texts(d):
    """Validate `default_layout['texts']` in whichever of its two shapes it takes.

    The bare `{text_key: str}` map is normalised into full boxes by
    `_texts_defaults`, so nothing there can be missing. The full-box LIST form is
    passed through UNCHANGED, straight into `clean_texts`, which does
    `{e['id']: e for e in defaults}` and then subscripts `base['text']`,
    `base['x']`, `base['y']`, `base['fontSize']`, `base['bold']`, `base['hidden']`
    in `_merge_text`. A list entry missing any of those is a KeyError -- and
    `get_layout`'s unset branch sits OUTSIDE its try/except, so that is an
    uncaught 500 on the print page, which is where the designer that could fix
    the layout lives. Validating here is what makes `get_layout`'s "the defaults
    path cannot itself raise" comment true.
    """
    texts = d.get('texts')
    if texts is None:
        return
    where0 = "default_layout['texts']"
    if isinstance(texts, dict):
        for k, v in texts.items():
            if v is not None and not isinstance(v, str):
                raise ValueError(f'{where0}[{k!r}] is {v!r}; must be a string')
        return
    if not isinstance(texts, list):
        raise ValueError(f'{where0} is {texts!r}; must be a {{id: str}} map or a box list')
    for i, box in enumerate(texts):
        where = f'{where0}[{i}]'
        if not isinstance(box, dict):
            raise ValueError(f'{where} is {box!r}; must be a dict')
        if not isinstance(box.get('id'), str) or not box['id']:
            raise ValueError(f"{where} is missing a string 'id'")
        where = f'{where0}[{box["id"]!r}]'
        if not isinstance(box.get('text'), str):
            raise ValueError(f"{where} is missing a string 'text'")
        _check_num(box, 'x', SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, where)
        _check_num(box, 'y', 0, CANVAS_H, where)
        _check_num(box, 'fontSize', FONT_MIN, FONT_MAX, where)
        _check_bool(box, 'bold', where)
        _check_bool(box, 'hidden', where)


def _validate_default_layout(field_keys, d):
    """Raise ValueError if a module's declared defaults could not render.

    The sanitizer builds EVERY layout over these defaults and the print template
    subscripts the result directly (`date_formats[layout.dateFormat]`,
    `layout.fields[k]`), so a typo'd declaration is not a caught fallback -- it is
    a 500 on the print page, or (the `w` case) a silent 10px-wide field nobody
    sees until a physical print. Checking once at import time turns every one of
    those into a loud, named error at the moment the module is declared.
    """
    if not isinstance(d, dict):
        raise ValueError('default_layout must be a dict')

    if d.get('paper') not in ALLOWED_PAPERS:
        raise ValueError(
            f"default_layout['paper'] is {d.get('paper')!r}; must be one of {list(ALLOWED_PAPERS)}")

    if d.get('dateFormat') not in ALLOWED_DATE_FORMATS:
        raise ValueError(
            f"default_layout['dateFormat'] is {d.get('dateFormat')!r}; "
            f"must be one of {list(ALLOWED_DATE_FORMATS)}")

    page = d.get('page')
    declared_font = page.get('fontFamily') if isinstance(page, dict) else page
    if not isinstance(page, dict) or declared_font not in ALLOWED_FONTS:
        raise ValueError(
            f"default_layout['page']['fontFamily'] is {declared_font!r}; "
            'must be one of ALLOWED_FONTS')

    fields = d.get('fields')
    if not isinstance(fields, dict):
        raise ValueError("default_layout['fields'] must be a dict")
    for k in field_keys:
        box = fields.get(k)
        if not isinstance(box, dict):
            raise ValueError(f"default_layout['fields'][{k!r}] is missing")
        where = f"default_layout['fields'][{k!r}]"
        _check_num(box, 'x', SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, where)
        _check_num(box, 'y', 0, CANVAS_H, where)
        _check_num(box, 'w', WIDTH_MIN, WIDTH_MAX, where)
        _check_num(box, 'fontSize', FONT_MIN, FONT_MAX, where)
        _check_bool(box, 'bold', where)
        _check_bool(box, 'hidden', where, required=False)

    line_items = d.get('lineItems')
    if not isinstance(line_items, dict):
        raise ValueError("default_layout['lineItems'] must be a dict")
    where = "default_layout['lineItems']"
    _check_num(line_items, 'y', 0, CANVAS_H, where)
    _check_num(line_items, 'rowHeight', ROW_MIN, ROW_MAX, where)
    _check_num(line_items, 'fontSize', FONT_MIN, FONT_MAX, where)
    _check_bool(line_items, 'bold', where)

    columns = line_items.get('columns')
    if isinstance(columns, list):
        for i, col in enumerate(columns):
            # a non-STRING key is rejected, not merely a missing one: `_clean_columns`
            # builds its allow-list as a dict keyed on these, so an unhashable
            # declared key raises at build time instead of naming itself here.
            if not isinstance(col, dict) or not isinstance(col.get('key'), str) or not col['key']:
                raise ValueError(f"default_layout['lineItems']['columns'][{i}] needs a 'key'")
            where = f"default_layout['lineItems']['columns'][{col['key']!r}]"
            _check_num(col, 'x', SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, where)
            _check_num(col, 'width', WIDTH_MIN, WIDTH_MAX, where)
            _check_bool(col, 'visible', where, required=False)

    _validate_default_texts(d)


def build_layout_api(setting_key, field_keys, default_layout, audit_module, audit_identifier):
    """Return (sanitize_layout, get_layout, save_layout) bound to one document type.

    Everything these three do is identical across documents EXCEPT the setting
    key, the field list and the defaults -- which is why the eight existing
    per-module copies differ by only ~76 lines once their document names are
    normalised. A module declares its own identity and inherits the rest.

    `default_layout` is validated HERE (i.e. at import time of the declaring
    module) and must have this shape::

        {
            'paper': one of ALLOWED_PAPERS,
            'dateFormat': one of ALLOWED_DATE_FORMATS,
            'page': {'fontFamily': one of ALLOWED_FONTS},
            'fields': {                     # one entry per key in `field_keys`
                <field_key>: {'x': int, 'y': int, 'w': int,   # 'w' is REQUIRED
                              'fontSize': int, 'bold': bool,
                              'hidden': bool},               # 'hidden' optional
                ...
            },
            'lineItems': {
                'y': int, 'rowHeight': int, 'fontSize': int, 'bold': bool,
                'columns': [                # optional; omit/{} for no columns
                    {'key': str, 'x': int, 'width': int,
                     'visible': bool},      # 'visible' optional, defaults True
                    ...
                ],
            },
            'extras': [],
            'texts': {text_key: str, ...}       # the usual form; positions come
                                                # from TEXT_DEFAULT_XS/_Y
                     or [                       # or the FULL box list, in which
                        {'id': str, 'text': str,    # case EVERY key shown is
                         'x': int, 'y': int,        # REQUIRED on every entry --
                         'fontSize': int,           # clean_texts subscripts all
                         'bold': bool,              # of them, so a partial entry
                         'hidden': bool},           # is a KeyError, not a
                        ...                         # caught fallback
                     ],
        }

    Every numeric prop above must be an actual number (not a numeric string, not
    a bool) and must ALREADY be inside the range its sanitizer would clamp it to
    -- `_clamp`'s fallback arm returns the declared value untouched, so an
    out-of-range or unparseable declaration is never clamped, it just prints.

    Raises ValueError, naming the offending key, if any of that is wrong.
    """
    _validate_default_layout(field_keys, default_layout)

    def sanitize_layout(raw):
        """Return a fully-populated, validated layout built from `raw` over the defaults."""
        raw = raw if isinstance(raw, dict) else {}
        d = default_layout
        paper = raw.get('paper') if raw.get('paper') in ALLOWED_PAPERS else d['paper']
        date_fmt = raw.get('dateFormat') if raw.get('dateFormat') in ALLOWED_DATE_FORMATS else d['dateFormat']
        # `page` is isinstance-guarded like every sibling key: stored JSON of
        # {"page": "Arial, sans-serif"} or {"page": [1]} parses fine, so an
        # unguarded .get() here would AttributeError straight through
        # get_layout's fallback and 500 the print page (the designer UI lives ON
        # that page, so there would be no way back except editing the DB).
        raw_page = raw.get('page') if isinstance(raw.get('page'), dict) else {}
        font = raw_page.get('fontFamily')
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
            # NOTE this branch sits OUTSIDE the try below on purpose, and is only
            # safe because `_validate_default_layout` has already proven that
            # sanitizing the declaration cannot raise -- every value the
            # sanitizer and `clean_texts` subscript is checked for presence, type
            # AND range at build time. Weaken that validator and this line
            # becomes an uncaught 500 on the print page.
            return sanitize_layout(copy.deepcopy(default_layout))
        try:
            return sanitize_layout(json.loads(stored))
        except Exception:  # noqa: BLE001 -- deliberately fail-safe
            # ANY failure reading a stored layout must degrade to the defaults.
            # A narrower except is not fail-safe: the print page hosts the
            # designer, so a raise here leaves that branch with no UI to fix its
            # own layout with. The defaults path below cannot itself raise, for
            # the reason given above.
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
