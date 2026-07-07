"""Layout model for the CDV **check** pre-printed overlay.

The simplest member of the pre-printed-forms family: FIELD + TEXT keys only — NO line
band, NO journal-entry face (a check has neither). The layout is a sanitized JSON blob
in an app_settings row, sanitized on read AND write against these defaults.

Two things diverge from the voucher clones (see plans/2026-07-07-cdv-check-writer.md):
- **Keyed per cash/bank account**, not per branch: each bank's pre-printed check has
  different field geometry. `cd_check_layout:<cash_account_id>` overrides the Default
  (`cd_check_layout`); resolution is account -> Default -> hardcoded default.
- **Every field carries a `width`.** The amount-in-words line is the legally-operative
  amount (NIL Sec.17(b)); the print route uses `width` to refuse a clipped/overflowing
  legal line. (The voucher clones' fields have no width.)

The check is rendered to PDF (not HTML @page) for reliable registration; this module is
only the layout schema/persistence — the PDF renderer + print route live elsewhere.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'cd_check_layout'

CANVAS_W = 912
CANVAS_H = 1008
SAFE_MARGIN = 48   # printable inset; element x is clamped inside it
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 912

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

FIELD_KEYS = ['payee', 'check_date', 'amount_figures', 'amount_in_words', 'memo']

FIELD_LABELS = {
    'payee': 'Payee',
    'check_date': 'Date',
    'amount_figures': 'Amount (Figures)',
    'amount_in_words': 'Amount in Words',
    'memo': 'Memo',
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

# Check date MUST be MM-DD-YYYY per PCHC (the voucher clones have no dash variant).
DATE_FORMATS = {
    'mdy_dash': '%m-%d-%Y',
    'long':     '%d %B %Y',
    'medium':   '%b %d, %Y',
    'us':       '%m/%d/%Y',
    'iso':      '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50

DEFAULT_CHECK_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'mdy_dash',
    'extras': [],
    'texts': [],   # the bank stock supplies its own labels; add arbitrary text if needed
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    # Placeholder positions — the real geometry comes from the client's physical check
    # sample (Phase 0). All x >= SAFE_MARGIN. Each field has a width.
    'fields': {
        'payee':           {'x': 120, 'y': 180, 'fontSize': 11, 'bold': False, 'width': 380},
        'check_date':      {'x': 640, 'y': 90,  'fontSize': 11, 'bold': False, 'width': 160},
        'amount_figures':  {'x': 680, 'y': 180, 'fontSize': 12, 'bold': True,  'width': 160},
        'amount_in_words': {'x': 80,  'y': 232, 'fontSize': 11, 'bold': False, 'width': 740},
        'memo':            {'x': 120, 'y': 320, 'fontSize': 9,  'bold': False, 'width': 300},
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
        'width': _clamp(raw.get('width'), WIDTH_MIN, WIDTH_MAX, default['width']),
    }


def _clean_extras(raw):
    raw = raw if isinstance(raw, list) else []
    out = []
    for e in raw[:MAX_EXTRAS]:
        if not isinstance(e, dict) or e.get('key') not in FIELD_KEYS:
            continue
        out.append({
            'key': e['key'],
            'x': _clamp(e.get('x'), SAFE_MARGIN, CANVAS_W - SAFE_MARGIN, SAFE_MARGIN),
            'y': _clamp(e.get('y'), 0, CANVAS_H, 0),
            'fontSize': _clamp(e.get('fontSize'), FONT_MIN, FONT_MAX, 11),
            'bold': bool(e.get('bold', False)),
            'width': _clamp(e.get('width'), WIDTH_MIN, WIDTH_MAX, 200),
        })
    return out


def sanitize_layout(raw):
    """Return a fully-populated, validated check layout built from `raw` over the defaults."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT_CHECK_LAYOUT
    paper = raw.get('paper') if raw.get('paper') in ALLOWED_PAPERS else d['paper']
    date_fmt = raw.get('dateFormat') if raw.get('dateFormat') in ALLOWED_DATE_FORMATS else d['dateFormat']
    font = (raw.get('page') or {}).get('fontFamily')
    page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS}
    return {'paper': paper, 'dateFormat': date_fmt, 'extras': _clean_extras(raw.get('extras')),
            'texts': clean_texts(raw.get('texts'), DEFAULT_CHECK_LAYOUT['texts']),
            'page': page, 'fields': fields}


def _layout_key(account_id):
    """Per cash/bank account; None -> the Default layout key."""
    return f'{LAYOUT_SETTING_KEY}:{account_id}' if account_id is not None else LAYOUT_SETTING_KEY


def get_layout(account_id=None):
    """Resolve account-specific -> Default -> hardcoded default (all sanitized)."""
    for key in ([_layout_key(account_id), LAYOUT_SETTING_KEY] if account_id is not None
                else [LAYOUT_SETTING_KEY]):
        stored = AppSettings.get_setting(key)
        if stored:
            try:
                return sanitize_layout(json.loads(stored))
            except (ValueError, TypeError):
                break   # corrupt -> hardcoded default
    return copy.deepcopy(DEFAULT_CHECK_LAYOUT)


def save_layout(raw, username, account_id=None):
    """Sanitize, persist (per account; None = the Default), audit, and return the clean layout."""
    clean = sanitize_layout(raw)
    key = _layout_key(account_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=username)
    log_audit(module='cash_disbursements', action='update', record_id=None,
              record_identifier='cd_check_layout',
              old_values={'layout': old, 'account_id': account_id},
              new_values={'layout': json.dumps(clean), 'account_id': account_id},
              notes=f'CDV check layout updated (account {account_id})')
    return clean
