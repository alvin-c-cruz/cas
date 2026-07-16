"""Layout model for the Payslip pre-printed print designer (R-06 Payslips).

Clone-and-adapt of app/sales_invoices/preprinted_layout.py. The whole layout is
one JSON value in an app_settings row. Everything is sanitized on read AND write
against these defaults, so stored or POSTed JSON can never inject unknown keys,
out-of-range numbers, or an unlisted font, and a layout saved before a new field
existed still renders that field at its default.

Unlike the Sales Invoice source this is cloned from, a payslip has NO line-item
grid (no product/qty/UOM table) -- so every COLUMN_KEYS / lineItems concept from
that source is intentionally DROPPED here, not adapted.
"""
import copy
import json

from app.settings import AppSettings
from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts

LAYOUT_SETTING_KEY = 'payslip_preprinted_layout'

# Dot-matrix continuous-form stock: 9.5in x 10.5in. At 96dpi (CSS px) that is the
# canvas size, so what is dragged on screen maps 1:1 to the printed form.
CANVAS_W = 912      # 9.5in  @96dpi
CANVAS_H = 1008     # 10.5in @96dpi
SAFE_MARGIN = 48   # printable inset (tractor-feed margin); element x is clamped inside it
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, 912

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
    'employee_name', 'position', 'date_hired', 'tin', 'sss_no', 'philhealth_no', 'pagibig_no',
    'pay_period', 'pay_date',
    'basic_pay', 'gross_pay', 'sss_ee', 'philhealth_ee', 'pagibig_ee', 'wht',
    'sss_loan', 'pagibig_loan', 'net_pay',
    'ytd_gross', 'ytd_wht', 'ytd_net',
]

# Friendly names for the per-field show/hide strip.
FIELD_LABELS = {
    'employee_name': 'Employee Name', 'position': 'Position', 'date_hired': 'Date Hired',
    'tin': 'TIN', 'sss_no': 'SSS No.', 'philhealth_no': 'PhilHealth No.', 'pagibig_no': 'Pag-IBIG No.',
    'pay_period': 'Pay Period', 'pay_date': 'Pay Date',
    'basic_pay': 'Basic Pay', 'gross_pay': 'Gross Pay', 'sss_ee': 'SSS', 'philhealth_ee': 'PhilHealth',
    'pagibig_ee': 'Pag-IBIG', 'wht': 'Withholding Tax', 'sss_loan': 'SSS Loan',
    'pagibig_loan': 'Pag-IBIG Loan', 'net_pay': 'Net Pay',
    'ytd_gross': 'YTD Gross', 'ytd_wht': 'YTD Withholding Tax', 'ytd_net': 'YTD Net Pay',
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

# Date format for the date-hired / pay-date fields. key -> strftime. The dropdown
# labels are generated from a sample date so they always match. The JS live-preview
# mirrors these keys (payslip_preprinted_designer.js::fmtDate).
DATE_FORMATS = {
    'long':   '%d %B %Y',
    'medium': '%b %d, %Y',
    'us':     '%m/%d/%Y',
    'eu':     '%d/%m/%Y',
    'iso':    '%Y-%m-%d',
}
ALLOWED_DATE_FORMATS = tuple(DATE_FORMATS)

MAX_EXTRAS = 50   # duplicated field copies cap

# Free-text, LAYOUT-ONLY signature elements (not tied to the payslip record). Editable
# in the designer; the same text prints on every payslip.
TEXT_KEYS = ['preparer', 'checker', 'approver']
TEXT_LABELS = {'preparer': 'Preparer', 'checker': 'Checker', 'approver': 'Approver'}
TEXT_MAXLEN = 200

DEFAULT_PAYSLIP_PREPRINTED_LAYOUT = {
    'paper': 'continuous',
    'dateFormat': 'long',
    'extras': [],
    'texts': [
        {'id': 'preparer', 'text': 'Prepared by:', 'x': 60,  'y': 760, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'checker',  'text': 'Checked by:',  'x': 340, 'y': 760, 'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'approver', 'text': 'Received by:', 'x': 620, 'y': 760, 'fontSize': 10, 'bold': False, 'hidden': False},
    ],
    'page': {'fontFamily': '"Courier New", Courier, monospace'},
    # Two identity/period columns up top (left x=60, right x=520), then a lower band
    # (x=620) for the earnings/deductions figures, then a YTD band below it. All are
    # a cosmetic starting grid the designer UI lets a user drag-adjust afterward.
    'fields': {
        # Identity (left column)
        'employee_name':  {'x': 60,  'y': 50,  'fontSize': 12, 'bold': True},
        'position':       {'x': 60,  'y': 74,  'fontSize': 11, 'bold': False},
        'date_hired':     {'x': 60,  'y': 98,  'fontSize': 11, 'bold': False},
        'tin':            {'x': 60,  'y': 122, 'fontSize': 11, 'bold': False},
        'sss_no':         {'x': 60,  'y': 146, 'fontSize': 11, 'bold': False},
        'philhealth_no':  {'x': 60,  'y': 170, 'fontSize': 11, 'bold': False},
        'pagibig_no':     {'x': 60,  'y': 194, 'fontSize': 11, 'bold': False},
        # Period (right column)
        'pay_period':     {'x': 520, 'y': 50,  'fontSize': 12, 'bold': True},
        'pay_date':       {'x': 520, 'y': 74,  'fontSize': 11, 'bold': False},
        # Earnings / deductions figures (lower band)
        'basic_pay':      {'x': 620, 'y': 400, 'fontSize': 10, 'bold': False},
        'gross_pay':      {'x': 620, 'y': 424, 'fontSize': 10, 'bold': True},
        'sss_ee':         {'x': 620, 'y': 448, 'fontSize': 10, 'bold': False},
        'philhealth_ee':  {'x': 620, 'y': 472, 'fontSize': 10, 'bold': False},
        'pagibig_ee':     {'x': 620, 'y': 496, 'fontSize': 10, 'bold': False},
        'wht':            {'x': 620, 'y': 520, 'fontSize': 10, 'bold': False},
        'sss_loan':       {'x': 620, 'y': 544, 'fontSize': 10, 'bold': False},
        'pagibig_loan':   {'x': 620, 'y': 568, 'fontSize': 10, 'bold': False},
        'net_pay':        {'x': 620, 'y': 600, 'fontSize': 13, 'bold': True},
        # Year-to-date band
        'ytd_gross':      {'x': 620, 'y': 650, 'fontSize': 10, 'bold': False},
        'ytd_wht':        {'x': 620, 'y': 674, 'fontSize': 10, 'bold': False},
        'ytd_net':        {'x': 620, 'y': 698, 'fontSize': 10, 'bold': True},
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
    d = DEFAULT_PAYSLIP_PREPRINTED_LAYOUT
    paper = raw.get('paper') if raw.get('paper') in ALLOWED_PAPERS else d['paper']
    date_fmt = raw.get('dateFormat') if raw.get('dateFormat') in ALLOWED_DATE_FORMATS else d['dateFormat']
    font = (raw.get('page') or {}).get('fontFamily')
    page = {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily']}
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    fields = {k: _clean_box(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS}
    return {'paper': paper, 'dateFormat': date_fmt, 'extras': _clean_extras(raw.get('extras')),
            'texts': clean_texts(raw.get('texts'), DEFAULT_PAYSLIP_PREPRINTED_LAYOUT['texts']),
            'page': page, 'fields': fields}


def _layout_key(branch_id):
    """Per-branch setting key; None -> the legacy un-scoped key (back-compat)."""
    return f'{LAYOUT_SETTING_KEY}:{branch_id}' if branch_id is not None else LAYOUT_SETTING_KEY


def get_layout(branch_id=None):
    """Current sanitized layout for a branch (defaults if unset or corrupt)."""
    stored = AppSettings.get_setting(_layout_key(branch_id))
    if not stored:
        return copy.deepcopy(DEFAULT_PAYSLIP_PREPRINTED_LAYOUT)
    try:
        return sanitize_layout(json.loads(stored))
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_PAYSLIP_PREPRINTED_LAYOUT)


def save_layout(branch_id, layout, updated_by=None):
    """Sanitize, persist (per branch), audit, and return the clean layout.

    Signature differs from the Sales Invoice source's save_layout(raw, username,
    branch_id=None): the payslip caller (payslip_view / save_payslip_print_layout)
    and the Task-5 sanitizer tests both call save_layout(branch_id, layout,
    updated_by=...) -- branch_id leads and the actor kwarg is `updated_by`.
    """
    clean = sanitize_layout(layout)
    key = _layout_key(branch_id)
    old = AppSettings.get_setting(key)
    AppSettings.set_setting(key, json.dumps(clean), updated_by=updated_by)
    log_audit(module='payroll', action='update', record_id=None,
              record_identifier='payslip_preprinted_layout',
              old_values={'layout': old, 'branch_id': branch_id},
              new_values={'layout': json.dumps(clean), 'branch_id': branch_id},
              notes=f'Payslip pre-printed layout updated (branch {branch_id})')
    return clean
