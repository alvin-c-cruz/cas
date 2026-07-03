"""Legacy RIC COA -> CAS account specs (types, groups, contra + classification)."""
import re
from collections import OrderedDict
from dataclasses import dataclass, asdict
from scripts.ric_coa.proper_case import proper_case

# legacy account_type -> (CAS account_type, base classification)
TYPE_MAP = {
    'Cash and Cash Equivalents': ('Asset', 'Current'),
    'Trade Receivable':          ('Asset', 'Current'),
    'Other Current Assets':      ('Asset', 'Current'),
    'Fixed Assets':              ('Asset', 'Non-Current'),
    'Other Assets':              ('Asset', 'Non-Current'),
    'Accounts Payable':          ('Liability', 'Current'),
    'Other Current Liabilities': ('Liability', 'Current'),
    'Other Liabilities':         ('Liability', 'Non-Current'),
    "Stockholder's Equity":      ('Equity', None),
    'Revenues':                  ('Revenue', None),
    'Other Income':              ('Other Income', None),
    'Direct Materials':          ('Cost of Goods Sold', None),
    'Direct Labor':              ('Cost of Goods Sold', None),
    'Factory Overhead':          ('Cost of Goods Sold', None),
    'Selling Expenses':          ('Selling Expense', None),
    'Administrative Expenses':   ('Administrative Expense', None),
}

# group code -> (title, CAS type, classification)  [insertion = statement order]
GROUPS = OrderedDict([
    ('111',  ('Cash & Cash Equivalents',                     'Asset', 'Current')),
    ('112',  ('Trade Receivables',                           'Asset', 'Current')),
    ('112N', ('Advances & Non-Trade Receivables',            'Asset', 'Current')),
    ('113',  ('Inventory — Tincan',                          'Asset', 'Current')),
    ('114',  ('Inventory — Plastic',                         'Asset', 'Current')),
    ('115',  ('Factory & Maintenance Supplies',              'Asset', 'Current')),
    ('116',  ('Prepaid Expenses & Interest',                  'Asset', 'Current')),
    ('117',  ('Assets in Transit',                           'Asset', 'Current')),
    ('125',  ('Creditable Withholding Tax & Overpayments',   'Asset', 'Current')),
    ('126',  ('Input VAT & Tax Credits',                     'Asset', 'Current')),
    ('122',  ('Property, Plant & Equipment — at Cost',       'Asset', 'Non-Current')),
    ('123',  ('Accumulated Depreciation',                    'Asset', 'Non-Current')),
    ('124',  ('Investments',                                 'Asset', 'Non-Current')),
    ('211',  ('Accounts Payable',                            'Liability', 'Current')),
    ('219',  ('Other Current Liabilities',                   'Liability', 'Current')),
    ('221',  ('Tax & Withholding Payables',                  'Liability', 'Non-Current')),
    ('222',  ('Statutory & Loan Payables',                   'Liability', 'Non-Current')),
    ('311',  ("Stockholders' Equity",                        'Equity', None)),
    ('411',  ('Sales — Tincan',                              'Revenue', None)),
    ('412',  ('Sales — Plastic',                             'Revenue', None)),
    ('421',  ('Scrap Sales',                                 'Revenue', None)),
    ('511',  ('Other Income & Gains',                        'Other Income', None)),
    ('611',  ('Direct Materials',                            'Cost of Goods Sold', None)),
    ('621',  ('Direct Labor',                                'Cost of Goods Sold', None)),
    ('641',  ('Indirect Labor & Personnel Cost',             'Cost of Goods Sold', None)),
    ('651',  ('Manufacturing Overhead',                      'Cost of Goods Sold', None)),
    ('661',  ('Selling Expenses',                            'Selling Expense', None)),
    ('671',  ('Administrative Expenses',                     'Administrative Expense', None)),
])

# Legacy leaves whose proper-cased name duplicates a kept seed account (Account.name is
# UNIQUE). Owner decision 2026-07-03: SKIP these — seed 10212 / 30200 are canonical.
SKIP_CODES = {'12501', '32101'}   # Creditable Withholding Tax; Retained Earnings


def _prefix(number):
    return re.match(r'(\d+)', str(number)).group(1)[:3]


def assign_group(legacy_type, account_number):
    p = _prefix(account_number)
    if legacy_type == 'Cash and Cash Equivalents': return '111'
    if legacy_type == 'Trade Receivable':          return '112'
    if legacy_type == 'Other Current Assets':
        return {'112':'112N','113':'113','114':'114','115':'115','116':'116','117':'117'}[p]
    if legacy_type == 'Fixed Assets':              return '123' if p == '123' else '122'
    if legacy_type == 'Other Assets':              return {'124':'124','125':'125','126':'126'}[p]
    if legacy_type == 'Accounts Payable':          return '211'
    if legacy_type == 'Other Current Liabilities': return '219'
    if legacy_type == 'Other Liabilities':         return '221' if p == '221' else '222'
    if legacy_type == "Stockholder's Equity":      return '311'
    if legacy_type == 'Revenues':                  return {'411':'411','412':'412','421':'421'}[p]
    if legacy_type == 'Other Income':              return '511'
    if legacy_type == 'Direct Materials':          return '611'
    if legacy_type == 'Direct Labor':              return '621'
    if legacy_type == 'Factory Overhead':          return '641' if p == '641' else '651'
    if legacy_type == 'Selling Expenses':          return '661'
    if legacy_type == 'Administrative Expenses':   return '671'
    raise KeyError(f'unmapped legacy type: {legacy_type!r}')


@dataclass
class AccountSpec:
    code: str
    name: str
    account_type: str
    classification: str | None
    normal_balance: str
    parent_code: str | None
    is_group: bool
    def as_dict(self):
        return asdict(self)


def _is_contra(group_code, number):
    return group_code == '123' or str(number) == '11202'


def build_accounts(legacy_rows):
    from app.accounts.account_types import DEFAULT_NORMAL_BALANCE
    rows = [(n, t, lt) for (n, t, lt) in legacy_rows if str(n) not in SKIP_CODES]
    specs = []
    used = OrderedDict()  # preserve GROUPS order, only used codes
    for num, title, ltype in rows:
        used[assign_group(ltype, num)] = True
    for code in GROUPS:
        if code in used:
            title, ct, cls = GROUPS[code]
            specs.append(AccountSpec(code, title, ct, cls,
                                     DEFAULT_NORMAL_BALANCE[ct], None, True))
    for num, title, ltype in rows:
        code = assign_group(ltype, num)
        _gt, ct, cls = GROUPS[code]
        nb = 'credit' if _is_contra(code, num) else DEFAULT_NORMAL_BALANCE[ct]
        specs.append(AccountSpec(str(num), proper_case(title), ct, cls, nb, code, False))
    return specs
