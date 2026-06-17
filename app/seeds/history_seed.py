"""Historical APV + CDV demo-data generator (2021 -> present).

Builds documents and posts them through the real posting helpers so every
journal entry balances exactly like a hand-entered voucher. See
docs/superpowers/specs/2026-06-18-apv-cdv-history-seed-design.md.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.users.models import User

TWO = Decimal('0.01')


def _money(x):
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


# code, name, category, vat_code, wht_code, cadence, amount_min, amount_max, expense_code
VENDORS = [
    {'code': 'HV-RENT', 'name': 'Sunrise Realty Mgmt',  'category': 'rent',      'vat_code': 'VATABLE',    'wht_code': 'WC040', 'cadence': 'monthly',    'amount_min': 40000, 'amount_max': 50000, 'expense_code': '50220'},
    {'code': 'HV-POWR', 'name': 'MetroPower Electric',  'category': 'utilities', 'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'monthly',    'amount_min': 8000,  'amount_max': 13000, 'expense_code': '50221'},
    {'code': 'HV-WATR', 'name': 'ClearWater Utilities', 'category': 'utilities', 'vat_code': 'VAT-EXEMPT', 'wht_code': None,    'cadence': 'monthly',    'amount_min': 1500,  'amount_max': 4000,  'expense_code': '50222'},
    {'code': 'HV-TELE', 'name': 'GlobeLink Telecom',    'category': 'telecom',   'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'monthly',    'amount_min': 3000,  'amount_max': 6000,  'expense_code': '50223'},
    {'code': 'HV-SUP1', 'name': 'Mega Office Supplies', 'category': 'supplies',  'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 5000,  'amount_max': 20000, 'expense_code': '50230'},
    {'code': 'HV-SUP2', 'name': 'Capitol Stationers',   'category': 'supplies',  'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 3000,  'amount_max': 12000, 'expense_code': '50230'},
    {'code': 'HV-FUEL', 'name': 'FleetFuel Station',    'category': 'fuel',      'vat_code': 'VATABLE',    'wht_code': None,    'cadence': 'frequent',   'amount_min': 4000,  'amount_max': 15000, 'expense_code': '50281'},
    {'code': 'HV-COUR', 'name': 'QuickCourier Express', 'category': 'courier',   'vat_code': 'VATABLE',    'wht_code': 'WC070', 'cadence': 'frequent',   'amount_min': 1500,  'amount_max': 5000,  'expense_code': '50280'},
    {'code': 'HV-TECH', 'name': 'TechServe IT Solutions','category': 'it',       'vat_code': 'VATABLE',    'wht_code': 'WC060', 'cadence': 'occasional', 'amount_min': 15000, 'amount_max': 55000, 'expense_code': '50270'},
    {'code': 'HV-LAW',  'name': 'Bautista Law Office',  'category': 'legal',     'vat_code': 'VATABLE',    'wht_code': 'WC010', 'cadence': 'occasional', 'amount_min': 20000, 'amount_max': 60000, 'expense_code': '50241'},
    {'code': 'HV-FIX',  'name': 'FixIt Maintenance',    'category': 'repairs',   'vat_code': 'VATABLE',    'wht_code': 'WC060', 'cadence': 'occasional', 'amount_min': 5000,  'amount_max': 30000, 'expense_code': '50270'},
    {'code': 'HV-ADV',  'name': 'BrightAd Marketing',   'category': 'marketing', 'vat_code': 'VATABLE',    'wht_code': 'WC070', 'cadence': 'occasional', 'amount_min': 10000, 'amount_max': 45000, 'expense_code': '50290'},
]

_EXPENSE_CODES = sorted({v['expense_code'] for v in VENDORS})


def resolve_refs():
    """Resolve the GL accounts the seed posts against. Raises if any are missing."""
    def need(code):
        a = Account.query.filter_by(code=code).first()
        if a is None:
            raise RuntimeError(f"Required account {code} missing — run seed-db first.")
        return a

    refs = {
        'ap': need('20101'),
        'wt': need('20301'),
        'input_vat': need('10501'),
        'cash_on_hand': need('10101'),
        'cash_in_bank': need('10110'),
        'expense': {code: need(code) for code in _EXPENSE_CODES},
    }
    return refs


def next_doc_number(prefix, doc_date, counters):
    """Return PREFIX-YYYY-MM-NNNN, sequencing per (prefix, year, month)."""
    key = (prefix, doc_date.year, doc_date.month)
    counters[key] = counters.get(key, 0) + 1
    return f'{prefix}-{doc_date.year}-{doc_date.month:02d}-{counters[key]:04d}'


def ensure_accountant_user():
    u = User.query.filter_by(username='accountant').first()
    if u is None:
        u = User(username='accountant', email='accountant@cas.local',
                 full_name='Maria Accountant', role='accountant', is_active=True)
        u.set_password('cas-accountant')
        db.session.add(u)
        db.session.commit()
    return u


def ensure_vendors():
    out = []
    for spec in VENDORS:
        v = Vendor.query.filter_by(code=spec['code']).first()
        if v is None:
            v = Vendor(code=spec['code'], name=spec['name'],
                       tin=f"{abs(hash(spec['code'])) % 900 + 100}-000-000-000",
                       payment_terms='Net 30',
                       default_vat_category=spec['vat_code'],
                       is_active=True)
            db.session.add(v)
        out.append(v)
    db.session.commit()
    return out
