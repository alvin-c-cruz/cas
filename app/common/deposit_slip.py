"""Deposit slip print-over: the forms, their layouts, and the values a slip carries.

Owner, 9 Nov 2026: "we will create a deposit slip in CAS ... it will be printed over the deposit
slip, like the check and vouchers"; Epson LQ-310, Edge, Letter, margins None; one slip per
cheque; no X marks. 10 Nov 2026: slips print from a CDV and from a CRV ("CAS-Q1: CRV, CDV,
both"), one layout per bank form set in a designer ("CAS-Q2, yes"), the date blank unless asked
for ("CAS-Q3, yes"); the design was approved as written ("CAS-D, approve as is").
Design: app-docs/superpowers/specs/2026-11-10-deposit-slip-print-design.md (beside the checkout).

A layout has the cheque layout's shape (fields with x/y/fontSize/bold/width, free texts, a font,
a date format), so the cheque designer (cd_check_designer.js) edits it unchanged. Two things
differ: each field has an `align` (the Chinabank amount ends at its column's right border), and
the page carries a whole-print nudge in mm (`offsetX`/`offsetY`), applied on paper only, for a
printer that lands every field a little off (the 9 Nov test print sat 1.2 mm low).
"""
import copy
import json
import re

from app.audit.utils import log_audit
from app.common.preprinted_texts import clean_texts
from app.settings import AppSettings

SETTING_PREFIX = 'deposit_slip_layout'

PX_PER_MM = 96 / 25.4
CANVAS_W, CANVAS_H = 816, 1056            # Letter at 96 px per inch
FONT_MIN, FONT_MAX = 6, 72
WIDTH_MIN, WIDTH_MAX = 10, CANVAS_W
OFFSET_MAX_MM = 20.0
ALIGNS = ('left', 'right')

FONT_GROUPS = [
    ('Deposit slip', ['"Arial Narrow", Arial, sans-serif']),
    ('Dot-matrix friendly', [
        '"Courier New", Courier, monospace',
        'Consolas, "Courier New", monospace',
        '"Lucida Console", Monaco, monospace',
    ]),
    ('Standard', [
        'Arial, sans-serif',
        'Calibri, Candara, "Segoe UI", sans-serif',
        'Tahoma, Geneva, sans-serif',
        'Verdana, Geneva, sans-serif',
        '"Times New Roman", Times, serif',
    ]),
]
ALLOWED_FONTS = [f for _label, fonts in FONT_GROUPS for f in fonts]

DATE_FORMATS = {
    'us':       '%m/%d/%Y',
    'mdy_dash': '%m-%d-%Y',
    'medium':   '%b %d, %Y',
    'full':     '%B %d, %Y',
}

FIELD_KEYS = ['deposit_date', 'account_name', 'account_number', 'total_amount',
              'check_bank', 'check_number', 'check_amount']
FIELD_LABELS = {
    'deposit_date': 'Date',
    'account_name': 'Account Name',
    'account_number': 'Account Number',
    'total_amount': 'Total Amount',
    'check_bank': 'Bank/Branch',
    'check_number': 'Check No.',
    'check_amount': 'Amount',
}

# The interim slips' fonts and offset (clients/philgen/forms/deposit-slips, 9 Nov 2026):
# Arial Narrow bold 10 pt, a field's top 0.86 em above its baseline, and the whole print
# raised 1.2 mm after the first test print on the LQ-310.
_FONT_PT = 10
_FONT_PX = int(_FONT_PT * 96 / 72)               # 13
_TOP_ABOVE_BASELINE_MM = 0.86 * _FONT_PT * 25.4 / 72 + 1.2


def _px(mm):
    return int(round(mm * PX_PER_MM))


def _field(x_mm, baseline_mm, width_px, align='left'):
    """A field from the interim slip's measurement: x (or the right edge when right-aligned)
    and the baseline, in mm from the slip's top-left."""
    x = _px(x_mm) - width_px if align == 'right' else _px(x_mm)
    return {'x': x, 'y': _px(baseline_mm - _TOP_ABOVE_BASELINE_MM), 'fontSize': _FONT_PX,
            'bold': True, 'hidden': False, 'width': width_px, 'align': align}


def _layout(fields):
    return {'paper': 'letter', 'dateFormat': 'us', 'extras': [], 'texts': [],
            'page': {'fontFamily': ALLOWED_FONTS[0], 'offsetX': 0.0, 'offsetY': 0.0},
            'fields': {k: fields[k] for k in FIELD_KEYS}}


FORMS = {
    # Chinabank Check Deposit Slip, BNK-108 (05-24) P/N, about 226 x 97 mm; the stub right of
    # the perforation gets nothing. Positions: the work order's table.
    'chinabank_bnk108': {
        'label': 'Chinabank Check Deposit Slip (BNK-108)',
        'aliases': ('CBC', 'CHINABANK'),
        'default': _layout({
            'deposit_date':   _field(11.0, 20.5, 120),
            'account_name':   _field(72.0, 46.0, 260),
            'account_number': _field(11.0, 52.5, 220),
            'total_amount':   _field(11.0, 64.0, 200),
            'check_bank':     _field(13.0, 83.6, 200),
            'check_number':   _field(69.0, 83.6, 140),
            'check_amount':   _field(139.0, 83.6, 113, align='right'),
        }),
    },
    # BDO Check Transaction Slip, form V062019, 216.3 x 103.6 mm. Positions:
    # interim/ub_3586838.json. The LQ-310 prints 8in wide, so the amounts are written
    # left-aligned at 187 mm rather than right-aligned at the column border.
    'bdo_v062019': {
        'label': 'BDO Check Transaction Slip (V062019)',
        'aliases': ('BDO', 'BANCODEORO'),
        'default': _layout({
            'deposit_date':   _field(192.0, 14.5, 88),
            'account_name':   _field(36.0, 22.0, 360),
            'account_number': _field(36.0, 30.0, 300),
            'total_amount':   _field(187.0, 92.0, 105),
            'check_bank':     _field(132.5, 37.0, 105),
            'check_number':   _field(161.5, 37.0, 95),
            'check_amount':   _field(187.0, 37.0, 105),
        }),
    },
}


def form_for_bank(bank_name):
    """The form of the bank a free-text bank name names, or None (blank, or a bank with no
    form yet). Letters and digits only, upper-cased, matched at the start against each form's
    aliases: 'China Bank', 'CBC / EASTWOOD' and 'Chinabank' are Chinabank; 'BDO Unibank' and
    'Banco de Oro' are BDO; 'BPI' and 'METROBANK' are None (owner, 10 Nov 2026: "VS-3 A")."""
    name = re.sub(r'[^A-Z0-9]', '', (bank_name or '').upper())
    if not name:
        return None
    for key, form in FORMS.items():
        if any(name.startswith(alias) for alias in form['aliases']):
            return key
    return None


def default_form_for(bank_name):
    """The form a slip starts on, from the bank of the account deposited into: the first
    form when the bank is blank or has no form."""
    return form_for_bank(bank_name) or next(iter(FORMS))


def pick_form(chosen, bank_name, payee='vendor'):
    """(form, notice) for a payee's slip (owner, 10 Nov 2026: "VS-1 A, VS-2 A, VS-3 A"). The
    form set on the payee (a vendor or an employee) wins; a blank one (or one no longer in
    FORMS) follows the bank name. A named bank with no form starts on the first form with a
    notice, never quietly."""
    if chosen in FORMS:
        return chosen, ''
    known = form_for_bank(bank_name)
    if known:
        return known, ''
    if not (bank_name or '').strip():
        return next(iter(FORMS)), ''
    return next(iter(FORMS)), (f"No slip form set for this {payee}'s bank ({bank_name.strip()}); "
                               f"choose one here or in {payee} maintenance.")


def deposit_to_line(bank_name, account_name, account_number):
    """The screen's one-line answer to "which account does this go into?" (owner, 10 Nov 2026:
    "...fill in the deposit slip with account number as well as the receipt's bank, ei. CBC or
    BDO"). Neither form has a receiving-bank box, so the bank is named here, not printed."""
    bank = (bank_name or '').strip() or 'bank not on file'
    name = (account_name or '').strip() or 'name not on file'
    number = (account_number or '').strip() or 'account number not on file'
    return f'Deposit to: {bank} — {name}, {number}'


def default_layout(form_key):
    return copy.deepcopy(FORMS[form_key]['default'])


def _clamp(value, lo, hi, fallback):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return max(lo, min(hi, n))


def _offset(value):
    try:
        mm = round(float(value), 1)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if mm != mm:          # NaN
        return 0.0
    return max(-OFFSET_MAX_MM, min(OFFSET_MAX_MM, mm))


def _clean_field(raw, default):
    raw = raw if isinstance(raw, dict) else {}
    align = raw.get('align', default['align'])
    return {
        'x': _clamp(raw.get('x'), 0, CANVAS_W, default['x']),
        'y': _clamp(raw.get('y'), 0, CANVAS_H, default['y']),
        'fontSize': _clamp(raw.get('fontSize'), FONT_MIN, FONT_MAX, default['fontSize']),
        'bold': bool(raw.get('bold', default['bold'])),
        'hidden': bool(raw.get('hidden', default['hidden'])),
        'width': _clamp(raw.get('width'), WIDTH_MIN, WIDTH_MAX, default['width']),
        'align': align if align in ALIGNS else default['align'],
    }


def sanitize_layout(form_key, raw):
    """A full, valid layout for `form_key` built from `raw` over that form's default."""
    d = FORMS[form_key]['default']
    raw = raw if isinstance(raw, dict) else {}
    page = raw.get('page') if isinstance(raw.get('page'), dict) else {}
    font = page.get('fontFamily')
    raw_fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else {}
    return {
        'paper': 'letter',
        'dateFormat': raw.get('dateFormat') if raw.get('dateFormat') in DATE_FORMATS else d['dateFormat'],
        'extras': [],
        'texts': clean_texts(raw.get('texts'), d['texts']),
        'page': {'fontFamily': font if font in ALLOWED_FONTS else d['page']['fontFamily'],
                 'offsetX': _offset(page.get('offsetX', 0)),
                 'offsetY': _offset(page.get('offsetY', 0))},
        'fields': {k: _clean_field(raw_fields.get(k), d['fields'][k]) for k in FIELD_KEYS},
    }


def _key(form_key):
    return f'{SETTING_PREFIX}:{form_key}'


def get_layout(form_key):
    """The form's saved layout, or its default."""
    FORMS[form_key]   # KeyError for an unknown form
    stored = AppSettings.get_setting(_key(form_key))
    if stored:
        try:
            return sanitize_layout(form_key, json.loads(stored))
        except (ValueError, TypeError):
            pass
    return default_layout(form_key)


def _money(value):
    from decimal import Decimal
    return '{:,.2f}'.format(Decimal(str(value or 0)))


def _bank_account_for(gl_account_id):
    from app.bank_accounts.models import BankAccount
    return BankAccount.query.filter_by(account_id=gl_account_id).first() if gl_account_id else None


# The CDV slip's Bank/Branch, kept per GL cash account (owner, 13 Nov 2026: "BB-1 A"; work order
# 2026-11-13-cdv-deposit-slip-bank-branch). A company's cheques name their own bank and branch
# (Philgen: "CBC/Eastwood this is the bank/branch of both our bank account"), which the voucher's
# Bank box ("CHINA BANK") does not, and a value typed on the slip lasts one print. Keyed by the GL
# account, not the branch: one cash account can serve two branches. Works with the Bank Accounts
# module off. Data, not code: each client keeps its own from the slip page.
BANK_SETTING_PREFIX = 'deposit_slip_bank'
BANK_MAX = 100              # the voucher's own Bank column (check_bank, String(100))


def _bank_key(cash_account_id):
    return f'{BANK_SETTING_PREFIX}:{cash_account_id}'


def kept_bank(cash_account_id):
    """The Bank/Branch kept for a cash account's slips, or ''."""
    if not cash_account_id:
        return ''
    return (AppSettings.get_setting(_bank_key(cash_account_id)) or '').strip()


def cash_account_label(cash_account_id):
    """'<code> <name>' of a GL cash account, as the slip page names it."""
    from app import db
    from app.accounts.models import Account
    account = db.session.get(Account, cash_account_id) if cash_account_id else None
    return f'{account.code} {account.name}' if account else 'this cash account'


def keep_bank(cash_account_id, text, username):
    """Keep `text` as the Bank/Branch of every slip on the cash account; blank clears it.
    Trimmed and cut to the voucher's Bank length; audited old -> new. Returns the kept value."""
    from app import db
    clean = ('' if text is None else str(text)).strip()[:BANK_MAX]
    key = _bank_key(cash_account_id)
    row = AppSettings.query.filter_by(key=key).first()
    old = row.value if row else ''
    if clean:
        AppSettings.set_setting(key, clean, updated_by=username)
    elif row:
        db.session.delete(row)
        db.session.commit()
    log_audit(module='cash_disbursements', action='update', record_id=None, record_identifier=key,
              old_values={'bank': old}, new_values={'bank': clean},
              notes=(f'Deposit slip Bank/Branch {"kept" if clean else "cleared"} for '
                     f'{cash_account_label(cash_account_id)}'))
    return clean


def cdv_check_bank(cdv, bank_acct=None):
    """(Bank/Branch, the line saying where it came from) for a CDV's slip: the value kept for
    its cash account, else the Bank Accounts master's bank name, else the voucher's Bank."""
    label = cash_account_label(cdv.cash_account_id)
    kept = kept_bank(cdv.cash_account_id)
    if kept:
        return kept, f'Kept for {label}.'
    bank_acct = bank_acct or _bank_account_for(cdv.cash_account_id)
    master = (bank_acct.bank_name or '').strip() if bank_acct else ''
    if master:
        return master, f'From Bank Accounts for {label}.'
    return cdv.check_bank or '', f"From this voucher's Bank. Nothing kept for {label}."


def cdv_payee(cdv):
    """The CDV's payee master row, a Vendor or an Employee, or None. A vendor comes through
    vendor_id, as before employees were added; an employee through payee_id."""
    if cdv.payee_type == 'employee':
        return cdv.payee
    return cdv.vendor if cdv.payee_type == 'vendor' else None


def cdv_values(cdv):
    """(values, deposit bank) for Philgen's own cheque deposited into the payee's account.

    The payee's account, from the vendor's or the employee's bank details (employees since
    10 Nov 2026, "EMP-B"): the bank account name, else a vendor's cheque payee name, else the
    payee; the bank account number, or blank to be typed (Resaida on V151 PETTY CASH has
    none). The cheque's bank: cdv_check_bank (the value kept for the CDV's cash account, else
    the Bank Accounts master's bank name, else the CDV's cheque bank).
    """
    payee = cdv_payee(cdv)
    name = ((payee.bank_account_name or '').strip()
            or ((payee.check_payee_name or '').strip() if cdv.payee_type == 'vendor' else '')) if payee else ''
    bank_acct = _bank_account_for(cdv.cash_account_id)
    amount = _money(cdv.total_amount)
    values = {
        'deposit_date': '',
        'account_name': name or cdv.vendor_name or '',
        'account_number': ((payee.bank_account_number or '').strip() if payee else ''),
        'total_amount': amount,
        'check_bank': cdv_check_bank(cdv, bank_acct)[0],
        'check_number': (cdv.check_number or '').strip(),
        'check_amount': amount,
    }
    return values, ((payee.bank_name or '') if payee else '')


def crv_values(crv):
    """(values, deposit bank) for a customer's cheque deposited into the company's account.

    The account: the company name, and the Bank Accounts master's number for the CRV's
    cash account (blank to be typed when the master has none: Philgen's was empty on
    9 Nov 2026). The cheque: the CRV's cheque bank and number.
    """
    bank_acct = _bank_account_for(crv.cash_account_id)
    amount = _money(crv.total_amount)
    values = {
        'deposit_date': '',
        'account_name': AppSettings.get_setting('company_name', '') or '',
        'account_number': ((bank_acct.account_number or '').strip() if bank_acct else ''),
        'total_amount': amount,
        'check_bank': crv.check_bank or '',
        'check_number': (crv.check_number or '').strip(),
        'check_amount': amount,
    }
    return values, (bank_acct.bank_name if bank_acct else '')


def render_slip(title, form_key, values, form_url, save_url, notice='', deposit_to='', bank_keep=None):
    """The slip page: the values at the form's layout positions, editable before printing;
    for full-access users it doubles as the layout designer, as the cheque page does.
    `bank_keep` (a CDV slip only: {'source', 'account', 'url'}) adds the line under Bank/Branch
    saying where it came from and, for full access, the Keep button."""
    from datetime import date
    from flask import render_template
    from flask_login import current_user
    from app.utils import ph_now
    layout = get_layout(form_key)
    return render_template(
        'deposit_slip_print.html', title=title, form_key=form_key, forms=FORMS, layout=layout,
        values=values, field_labels=FIELD_LABELS, font_groups=FONT_GROUPS,
        date_formats=DATE_FORMATS,
        date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()},
        today=ph_now().date(), form_url=form_url, save_url=save_url, notice=notice, deposit_to=deposit_to,
        bank_keep=bank_keep, can_edit_layout=current_user.has_full_access)


def save_layout(form_key, raw, username):
    """Sanitize, persist, audit, and return the clean layout."""
    clean = sanitize_layout(form_key, raw)
    old = AppSettings.get_setting(_key(form_key))
    AppSettings.set_setting(_key(form_key), json.dumps(clean), updated_by=username)
    log_audit(module='cash_disbursements', action='update', record_id=None,
              record_identifier=_key(form_key),
              old_values={'layout': old}, new_values={'layout': json.dumps(clean)},
              notes=f'Deposit slip layout updated ({FORMS[form_key]["label"]})')
    return clean
