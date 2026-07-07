# Clean Copy — Firm + Software COA + `seed-firm` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested `flask seed-firm` command that seeds a clean CAS database with a combined accounting-firm + software-company Chart of Accounts (+ PH VAT/EWT + placeholder identity), then deploy that clean copy to the user's PythonAnywhere account.

**Architecture:** New data module `app/seeds/firm_coa.py` (`FIRM_COA`, same 6-tuple shape as `BASELINE_COA`). Refactor `app/seeds/seed_data.py` to extract shared helpers so `seed_minimal` (unchanged output) and a new `seed_firm` differ only in COA list + `company_name`. Register `seed-firm` as a CLI command. Deploy to PythonAnywhere via the CAS git-based multi-instance flow, driven through Chrome MCP.

**Tech Stack:** Flask CLI, SQLAlchemy, SQLite, pytest.

## Global Constraints

- **No schema/model changes.** Data + a new CLI command only. (If any model edit seems needed, STOP and ask.)
- **`Account.name` is UNIQUE** and `Account.code` is UNIQUE — no duplicates across `FIRM_COA`.
- **Hierarchy is derived:** a node is a non-postable GROUP if top-level (`parent is None`) OR has children; else a postable LEAF. Every account meant to receive postings must have a parent.
- **Six magic codes must exist at exact values:** `10201` (AR-Trade), `10212` (Creditable WHT), `20101` (AP-Trade), `20301` (WHT Payable-Expanded), `30201` (Retained Earnings-Unappropriated), `30301` (Current Year Earnings). Input/output VAT resolve via category pointers to `10501–10504` / `20201`.
- **`seed_minimal` output must stay byte-identical** (25 accounts, `company_name='Company Name'`, 7 input-VAT / 3 sales-VAT / 8 EWT) — pinned by a regression test.
- **`account_type` ∈ `ACCOUNT_TYPES`** (`app/accounts/account_types.py`); Asset/Liability carry `classification` ∈ {Current, Non-Current}; all other types carry `None`.
- **ASCII-only** in any file whose stdout hits the console (seed prints) — use `--`/`->`, not unicode glyphs.
- SQLAlchemy 2.0 spellings only (`db.session.get` / `db.get_or_404`), never `.query.get(...)`.
- Work on `main`, commit per task, do **not** push until the user says "push".

---

### Task 1: `firm_coa.py` data module + static validation tests

**Files:**
- Create: `app/seeds/firm_coa.py`
- Test: `tests/unit/test_firm_coa.py`

**Interfaces:**
- Produces: `FIRM_COA` — `list[tuple[str, str, str, str|None, str, str|None]]` = `(code, name, account_type, classification, normal_balance, parent_code)`. Consumed by `_seed_accounts()` in Task 2/3.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_firm_coa.py`

```python
import pytest
from app.seeds.firm_coa import FIRM_COA
from app.accounts.account_types import ACCOUNT_TYPES, TYPES_NEEDING_CLASSIFICATION

# code -> (expected account_type, expected normal_balance)
MAGIC_CODES = {
    '10201': ('Asset', 'debit'),
    '10212': ('Asset', 'debit'),
    '20101': ('Liability', 'credit'),
    '20301': ('Liability', 'credit'),
    '30201': ('Equity', 'credit'),
    '30301': ('Equity', 'credit'),
}
POSTABLE_MAGIC_LEAVES = ['10201', '10212', '20101', '20301', '30201']

def _codes():
    return [r[0] for r in FIRM_COA]

def _parents_used():
    return {r[5] for r in FIRM_COA if r[5] is not None}

def test_no_duplicate_codes():
    codes = _codes()
    assert len(codes) == len(set(codes))

def test_no_duplicate_names():
    names = [r[1] for r in FIRM_COA]
    assert len(names) == len(set(names))

def test_parents_resolve():
    codes = set(_codes())
    for code, name, atype, classification, nb, parent in FIRM_COA:
        if parent is not None:
            assert parent in codes, f"{code}: parent {parent} not in COA"

def test_magic_codes_present_with_correct_type_and_balance():
    by_code = {r[0]: r for r in FIRM_COA}
    for code, (atype, nb) in MAGIC_CODES.items():
        assert code in by_code, f"magic code {code} missing"
        assert by_code[code][2] == atype, f"{code}: type {by_code[code][2]} != {atype}"
        assert by_code[code][4] == nb, f"{code}: nb {by_code[code][4]} != {nb}"

def test_account_types_valid():
    for code, name, atype, classification, nb, parent in FIRM_COA:
        assert atype in ACCOUNT_TYPES, f"{code}: invalid type {atype}"

def test_classification_rule():
    for code, name, atype, classification, nb, parent in FIRM_COA:
        if atype in TYPES_NEEDING_CLASSIFICATION:
            assert classification in ('Current', 'Non-Current'), f"{code} needs classification"
        else:
            assert classification is None, f"{code} must have no classification"

def test_normal_balance_values():
    for code, name, atype, classification, nb, parent in FIRM_COA:
        assert nb in ('debit', 'credit'), f"{code}: bad normal_balance {nb}"

def test_postable_magic_codes_are_leaves():
    by_code = {r[0]: r for r in FIRM_COA}
    used = _parents_used()
    for code in POSTABLE_MAGIC_LEAVES:
        assert by_code[code][5] is not None, f"{code} must have a parent (be postable)"
        assert code not in used, f"{code} must be a leaf (no children)"

def test_no_orphan_top_level_leaves():
    # every top-level account must have children (be a group), EXCEPT 30301 which the
    # year-end close writes to programmatically.
    used = _parents_used()
    for code, name, atype, classification, nb, parent in FIRM_COA:
        if parent is None and code not in used:
            assert code == '30301', f"top-level {code} has no children -> non-postable orphan"

def test_ascii_only_names():
    for code, name, atype, classification, nb, parent in FIRM_COA:
        assert name.isascii(), f"{code}: non-ASCII name {name!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_firm_coa.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.seeds.firm_coa'`

- [ ] **Step 3: Write minimal implementation** — `app/seeds/firm_coa.py`

```python
"""Chart of Accounts for a combined accounting firm + software company (PH, VAT-registered).

Same 6-tuple shape as BASELINE_COA (seed_data.py) so _seed_accounts() can seed either:
    (code, name, account_type, classification, normal_balance, parent_code)

account_type carries the FS taxonomy (app/accounts/account_types.py); hierarchy is DERIVED
(top-level or has-children = non-postable group; else postable leaf) -- no stored is_header.
Contra accounts (Accumulated Depreciation/Amortization, Allowance, Drawings) carry the
opposite normal_balance. Six magic codes required by the posting engine are kept at their
exact values: 10201, 10212, 20101, 20301, 30201, 30301.
"""

FIRM_COA = [
    # ===== ASSETS - Current =====
    ('10100', 'Cash and Cash Equivalents',                  'Asset', 'Current', 'debit',  None),
    ('10101', 'Cash on Hand',                               'Asset', 'Current', 'debit',  '10100'),
    ('10102', 'Petty Cash Fund',                            'Asset', 'Current', 'debit',  '10100'),
    ('10110', 'Cash in Bank - Current Account',             'Asset', 'Current', 'debit',  '10100'),
    ('10111', 'Cash in Bank - Savings Account',             'Asset', 'Current', 'debit',  '10100'),
    ('10200', 'Trade and Other Receivables',                'Asset', 'Current', 'debit',  None),
    ('10201', 'Accounts Receivable - Trade',                'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10202', 'Allowance for Doubtful Accounts',            'Asset', 'Current', 'credit', '10200'),   # contra
    ('10210', 'Advances to Employees',                      'Asset', 'Current', 'debit',  '10200'),
    ('10211', 'Advances to Officers',                       'Asset', 'Current', 'debit',  '10200'),
    ('10212', 'Creditable Withholding Tax',                 'Asset', 'Current', 'debit',  '10200'),   # MAGIC
    ('10400', 'Prepaid Expenses and Other Current Assets',  'Asset', 'Current', 'debit',  None),
    ('10401', 'Prepaid Rent',                               'Asset', 'Current', 'debit',  '10400'),
    ('10402', 'Prepaid Insurance',                          'Asset', 'Current', 'debit',  '10400'),
    ('10403', 'Prepaid Software Subscriptions',             'Asset', 'Current', 'debit',  '10400'),
    ('10404', 'Other Current Assets',                       'Asset', 'Current', 'debit',  '10400'),
    ('10500', 'Input VAT',                                  'Asset', 'Current', 'debit',  None),
    ('10501', 'Input VAT - Capital Goods',                  'Asset', 'Current', 'debit',  '10500'),
    ('10502', 'Input VAT - Domestic Goods',                 'Asset', 'Current', 'debit',  '10500'),
    ('10503', 'Input VAT - Services',                       'Asset', 'Current', 'debit',  '10500'),
    ('10504', 'Input VAT - Importation',                    'Asset', 'Current', 'debit',  '10500'),
    # ===== ASSETS - Non-Current =====
    ('11100', 'Property and Equipment',                            'Asset', 'Non-Current', 'debit',  None),
    ('11110', 'Office Equipment',                                  'Asset', 'Non-Current', 'debit',  '11100'),
    ('11111', 'Accumulated Depreciation - Office Equipment',       'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11120', 'Computer Equipment',                               'Asset', 'Non-Current', 'debit',  '11100'),
    ('11121', 'Accumulated Depreciation - Computer Equipment',    'Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11130', 'Furniture and Fixtures',                          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11131', 'Accumulated Depreciation - Furniture and Fixtures','Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11140', 'Leasehold Improvements',                          'Asset', 'Non-Current', 'debit',  '11100'),
    ('11141', 'Accumulated Depreciation - Leasehold Improvements','Asset', 'Non-Current', 'credit', '11100'),  # contra
    ('11200', 'Intangible Assets',                                'Asset', 'Non-Current', 'debit',  None),
    ('11201', 'Capitalized Software Development Costs',           'Asset', 'Non-Current', 'debit',  '11200'),
    ('11202', 'Accumulated Amortization - Software Development Costs', 'Asset', 'Non-Current', 'credit', '11200'),  # contra
    ('11203', 'Software and Licenses',                           'Asset', 'Non-Current', 'debit',  '11200'),
    ('11204', 'Accumulated Amortization - Software and Licenses','Asset', 'Non-Current', 'credit', '11200'),  # contra
    ('11300', 'Other Non-Current Assets',                        'Asset', 'Non-Current', 'debit',  None),
    ('11301', 'Security Deposits',                               'Asset', 'Non-Current', 'debit',  '11300'),
    # ===== LIABILITIES - Current =====
    ('20100', 'Trade and Other Payables',                  'Liability', 'Current', 'credit', None),
    ('20101', 'Accounts Payable - Trade',                  'Liability', 'Current', 'credit', '20100'),  # MAGIC
    ('20102', 'Accounts Payable - Others',                 'Liability', 'Current', 'credit', '20100'),
    ('20103', 'Accrued Expenses',                          'Liability', 'Current', 'credit', '20100'),
    ('20104', 'Accrued Salaries and Wages',               'Liability', 'Current', 'credit', '20100'),
    ('20200', 'Output VAT',                                'Liability', 'Current', 'credit', None),
    ('20201', 'Output VAT - Sales',                        'Liability', 'Current', 'credit', '20200'),
    ('20202', 'VAT Payable',                               'Liability', 'Current', 'credit', '20200'),
    ('20300', 'Withholding and Other Taxes Payable',       'Liability', 'Current', 'credit', None),
    ('20301', 'Withholding Tax Payable - Expanded',        'Liability', 'Current', 'credit', '20300'),  # MAGIC
    ('20302', 'Withholding Tax Payable - Compensation',    'Liability', 'Current', 'credit', '20300'),
    ('20303', 'Income Tax Payable',                        'Liability', 'Current', 'credit', '20300'),
    ('20400', 'Statutory Payables',                        'Liability', 'Current', 'credit', None),
    ('20401', 'SSS Contributions Payable',                 'Liability', 'Current', 'credit', '20400'),
    ('20402', 'PhilHealth Contributions Payable',          'Liability', 'Current', 'credit', '20400'),
    ('20403', 'Pag-IBIG Contributions Payable',            'Liability', 'Current', 'credit', '20400'),
    ('20500', 'Unearned and Deferred Revenue',             'Liability', 'Current', 'credit', None),
    ('20501', 'Unearned Subscription Revenue',             'Liability', 'Current', 'credit', '20500'),
    ('20502', 'Unearned Service Revenue',                  'Liability', 'Current', 'credit', '20500'),
    # ===== LIABILITIES - Non-Current =====
    ('21100', 'Long-Term Liabilities',                     'Liability', 'Non-Current', 'credit', None),
    ('21101', 'Loans Payable',                             'Liability', 'Non-Current', 'credit', '21100'),
    ('21102', 'Lease Liability',                           'Liability', 'Non-Current', 'credit', '21100'),
    # ===== EQUITY =====
    ('30100', "Owners' Equity",                            'Equity', None, 'credit', None),
    ('30101', "Owners' Capital",                           'Equity', None, 'credit', '30100'),
    ('30102', "Owners' Drawings",                          'Equity', None, 'debit',  '30100'),  # contra
    ('30200', 'Retained Earnings',                         'Equity', None, 'credit', None),
    ('30201', 'Retained Earnings - Unappropriated',        'Equity', None, 'credit', '30200'),  # MAGIC
    ('30301', 'Current Year Earnings',                     'Equity', None, 'credit', None),      # MAGIC (top-level; close writes here)
    # ===== REVENUE =====
    ('40100', 'Accounting Services Revenue',               'Revenue', None, 'credit', None),
    ('40101', 'Bookkeeping Fees',                          'Revenue', None, 'credit', '40100'),
    ('40102', 'Audit and Assurance Fees',                  'Revenue', None, 'credit', '40100'),
    ('40103', 'Tax Compliance Fees',                       'Revenue', None, 'credit', '40100'),
    ('40104', 'Advisory and Consulting Fees',              'Revenue', None, 'credit', '40100'),
    ('40200', 'Software Revenue',                          'Revenue', None, 'credit', None),
    ('40201', 'Subscription (SaaS) Revenue',               'Revenue', None, 'credit', '40200'),
    ('40202', 'Software License Revenue',                  'Revenue', None, 'credit', '40200'),
    ('40203', 'Custom Development Revenue',                'Revenue', None, 'credit', '40200'),
    ('40204', 'Support and Maintenance Revenue',           'Revenue', None, 'credit', '40200'),
    ('40205', 'Implementation and Setup Revenue',          'Revenue', None, 'credit', '40200'),
    ('40300', 'Other Income',                              'Other Income', None, 'credit', None),
    ('40301', 'Interest Income',                           'Other Income', None, 'credit', '40300'),
    ('40302', 'Miscellaneous Income',                      'Other Income', None, 'credit', '40300'),
    # ===== COST OF SERVICES (Cost of Goods Sold) =====
    ('50100', 'Cost of Accounting Services',              'Cost of Goods Sold', None, 'debit', None),
    ('50101', 'Salaries - Professional Staff',            'Cost of Goods Sold', None, 'debit', '50100'),
    ('50102', 'Direct Engagement Costs',                  'Cost of Goods Sold', None, 'debit', '50100'),
    ('50150', 'Cost of Software Services',                'Cost of Goods Sold', None, 'debit', None),
    ('50151', 'Salaries - Developers',                    'Cost of Goods Sold', None, 'debit', '50150'),
    ('50152', 'Cloud Hosting and Infrastructure',        'Cost of Goods Sold', None, 'debit', '50150'),
    ('50153', 'Third-Party Software and API Costs',      'Cost of Goods Sold', None, 'debit', '50150'),
    ('50154', 'Amortization - Capitalized Software Development', 'Cost of Goods Sold', None, 'debit', '50150'),
    # ===== SELLING EXPENSE =====
    ('50210', 'Selling and Marketing Expenses',          'Selling Expense', None, 'debit', None),
    ('50211', 'Advertising and Marketing',               'Selling Expense', None, 'debit', '50210'),
    ('50212', 'Representation and Entertainment',        'Selling Expense', None, 'debit', '50210'),
    ('50213', 'Sales Commissions',                       'Selling Expense', None, 'debit', '50210'),
    # ===== ADMINISTRATIVE EXPENSE =====
    ('50220', 'General and Administrative Expenses',     'Administrative Expense', None, 'debit', None),
    ('50221', 'Salaries and Wages - Administrative',     'Administrative Expense', None, 'debit', '50220'),
    ('50222', 'SSS, PhilHealth and Pag-IBIG - Employer Share', 'Administrative Expense', None, 'debit', '50220'),
    ('50223', '13th Month Pay and Other Benefits',       'Administrative Expense', None, 'debit', '50220'),
    ('50224', 'Rent Expense',                            'Administrative Expense', None, 'debit', '50220'),
    ('50225', 'Utilities Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50226', 'Communications and Internet Expense',     'Administrative Expense', None, 'debit', '50220'),
    ('50227', 'Office Supplies Expense',                 'Administrative Expense', None, 'debit', '50220'),
    ('50228', 'Software Subscriptions - Internal Tools', 'Administrative Expense', None, 'debit', '50220'),
    ('50229', 'Depreciation Expense',                    'Administrative Expense', None, 'debit', '50220'),
    ('50230', 'Amortization Expense',                    'Administrative Expense', None, 'debit', '50220'),
    ('50231', 'Insurance Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50232', 'Taxes and Licenses',                      'Administrative Expense', None, 'debit', '50220'),
    ('50233', 'Professional Fees',                       'Administrative Expense', None, 'debit', '50220'),
    ('50234', 'Transportation and Travel',               'Administrative Expense', None, 'debit', '50220'),
    ('50235', 'Training and Seminars',                   'Administrative Expense', None, 'debit', '50220'),
    ('50236', 'Repairs and Maintenance',                 'Administrative Expense', None, 'debit', '50220'),
    ('50237', 'Bank Charges',                            'Administrative Expense', None, 'debit', '50220'),
    ('50238', 'Bad Debts Expense',                       'Administrative Expense', None, 'debit', '50220'),
    ('50239', 'Miscellaneous Expense',                   'Administrative Expense', None, 'debit', '50220'),
    # ===== OTHER EXPENSE =====
    ('50300', 'Other Expenses',                          'Other Expense', None, 'debit', None),
    ('50301', 'Interest Expense',                        'Other Expense', None, 'debit', '50300'),
    ('50302', 'Loss on Disposal of Assets',              'Other Expense', None, 'debit', '50300'),
    # ===== INCOME TAX EXPENSE =====
    ('50400', 'Income Tax Expense',                      'Income Tax Expense', None, 'debit', None),
    ('50401', 'Income Tax Expense - Current',            'Income Tax Expense', None, 'debit', '50400'),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_firm_coa.py -q`
Expected: PASS (all tests green). If a name/parent/type assertion fails, fix the offending tuple in `firm_coa.py` — do not weaken the test.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/firm_coa.py tests/unit/test_firm_coa.py
git commit -m "feat(seeds): FIRM_COA firm+software chart of accounts + validation tests"
```

---

### Task 2: Extract shared seed helpers (keep `seed_minimal` identical)

**Files:**
- Modify: `app/seeds/seed_data.py` (add helpers; rewrite `seed_minimal` body to call them)
- Test: `tests/unit/test_seed_minimal_regression.py`

**Interfaces:**
- Produces (module-level in `seed_data.py`): `_seed_admin_and_branch()`, `_seed_app_settings(company_name='Company Name')`, `_seed_accounts(coa_list)`, `_seed_vat_categories()`, `_seed_sales_vat_categories()`, `_seed_withholding_taxes()`. Consumed by `seed_minimal` (this task) and `seed_firm` (Task 3).

- [ ] **Step 1: Write the failing regression test** — `tests/unit/test_seed_minimal_regression.py`

```python
from app.seeds.seed_data import seed_minimal
from app.accounts.models import Account
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax

def test_seed_minimal_output_unchanged(db_session):
    seed_minimal()
    assert Account.query.count() == 25
    assert AppSettings.get_setting('company_name') == 'Company Name'
    assert VATCategory.query.count() == 7
    assert SalesVATCategory.query.count() == 3
    assert WithholdingTax.query.count() == 8
    # magic codes still present
    for code in ['10201', '10212', '20101', '20301', '30201', '30301']:
        assert Account.query.filter_by(code=code).first() is not None
```

- [ ] **Step 2: Run test to confirm current behavior (baseline green)**

Run: `pytest tests/unit/test_seed_minimal_regression.py -q`
Expected: PASS against the *current* `seed_minimal` (this is the baseline we must preserve). If it FAILS now, STOP — the assumptions about counts are wrong; re-check before refactoring.

- [ ] **Step 3: Add the helper functions** to `app/seeds/seed_data.py` (place them just above `def seed_minimal():`). Move the existing block bodies verbatim into these helpers:

```python
def _seed_admin_and_branch():
    """Create admin/admin123 + MAIN branch (idempotent); assign admin to the branch."""
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@cascorp.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    main_branch = Branch.query.filter_by(code='MAIN').first()
    if not main_branch:
        main_branch = Branch(code='MAIN', name='Main Branch', address='Head Office', is_active=True)
        db.session.add(main_branch)
        db.session.commit()
    if main_branch not in admin.branches.all():
        admin.branches.append(main_branch)
        db.session.commit()
    return admin, main_branch


def _seed_app_settings(company_name='Company Name'):
    """Seed the 24-row settings block (idempotent). company_name is parameterized."""
    if AppSettings.query.count() > 0:
        return
    settings = [
        {'key': 'company_name',         'value': company_name},
        {'key': 'trade_name',           'value': ''},
        {'key': 'company_tin',          'value': ''},
        {'key': 'tin_branch_code',      'value': '000'},
        {'key': 'rdo_code',             'value': ''},
        {'key': 'vat_registration_type','value': 'VAT'},
        {'key': 'company_address',      'value': ''},
        {'key': 'postal_code',          'value': ''},
        {'key': 'phone',                'value': ''},
        {'key': 'email',                'value': ''},
        {'key': 'fiscal_year_start',    'value': '01'},
        {'key': 'officer_president',    'value': ''},
        {'key': 'officer_treasurer',    'value': ''},
        {'key': 'officer_secretary',    'value': ''},
        {'key': 'apv_print_access',     'value': 'posted_only'},
        {'key': 'sv_print_access',      'value': 'posted_only'},
        {'key': 'sv_print_form',        'value': 'current'},
        {'key': 'cd_print_access',      'value': 'posted_only'},
        {'key': 'cd_check_print_access','value': 'posted_only'},
        {'key': 'cr_print_access',      'value': 'posted_only'},
        {'key': 'company_logo',         'value': ''},
        {'key': 'accountant_email_self_approval', 'value': '0'},
        {'key': 'module_enabled:bir_reports',      'value': '0'},
        {'key': 'module_enabled:units_of_measure', 'value': '0'},
        {'key': 'module_enabled:products',         'value': '0'},
    ]
    for s in settings:
        db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
    db.session.commit()


def _seed_accounts(coa_list):
    """Create every account (pass 1) then wire parents by code (pass 2). Idempotent."""
    if Account.query.count() > 0:
        return
    code_to_account = {}
    for code, name, atype, classification, nb, _parent in coa_list:
        acct = Account(code=code, name=name, account_type=atype,
                       classification=classification, normal_balance=nb, is_active=True)
        db.session.add(acct)
        code_to_account[code] = acct
    db.session.flush()
    for code, _n, _t, _c, _nb, parent in coa_list:
        if parent:
            code_to_account[code].parent_id = code_to_account[parent].id
    db.session.commit()


def _seed_vat_categories():
    """7 input VAT categories (idempotent); V12* point at input VAT accounts 10501-04."""
    if VATCategory.query.count() > 0:
        return
    vat_accounts = {a.code: a.id for a in Account.query.filter(
        Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
    vat_categories = [
        {'code': 'VEX',   'name': 'VAT Exempt',              'rate':  0.00, 'input_vat_account_id': None},
        {'code': 'V0',    'name': 'VAT Zero-Rated',          'rate':  0.00, 'input_vat_account_id': None},
        {'code': 'INV',   'name': 'Invalid',                 'rate':  0.00, 'input_vat_account_id': None},
        {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10501')},
        {'code': 'V12DG', 'name': 'Input Tax Domestic Goods','rate': 12.00, 'input_vat_account_id': vat_accounts.get('10502')},
        {'code': 'V12SV', 'name': 'Input Tax Services',      'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10503')},
        {'code': 'V12IM', 'name': 'Input Tax Importation',   'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10504')},
    ]
    for cat in vat_categories:
        db.session.add(VATCategory(code=cat['code'], name=cat['name'], rate=cat['rate'],
                                   description='', input_vat_account_id=cat['input_vat_account_id'],
                                   is_active=True))
    db.session.commit()


def _seed_sales_vat_categories():
    """3 sales VAT categories (idempotent); V12 points at output VAT account 20201."""
    from app.sales_vat_categories.models import SalesVATCategory
    if SalesVATCategory.query.count() > 0:
        return
    _out = Account.query.filter_by(code='20201').first()
    _out_id = _out.id if _out else None
    svat = [
        {'code': 'V12', 'name': 'VATable Sales (12%)',  'rate': 12.00, 'transaction_nature': 'regular',     'output_vat_account_id': _out_id},
        {'code': 'V0',  'name': 'VAT Zero-Rated Sales', 'rate':  0.00, 'transaction_nature': 'zero_export', 'output_vat_account_id': None},
        {'code': 'VEX', 'name': 'VAT-Exempt Sales',     'rate':  0.00, 'transaction_nature': 'exempt',      'output_vat_account_id': None},
    ]
    for cat in svat:
        db.session.add(SalesVATCategory(code=cat['code'], name=cat['name'], rate=cat['rate'],
                                        transaction_nature=cat['transaction_nature'],
                                        output_vat_account_id=cat['output_vat_account_id'], is_active=True))
    db.session.commit()


def _seed_withholding_taxes():
    """8 EWT codes (idempotent); backfill sales_name if codes already exist."""
    existing = {w.code: w for w in WithholdingTax.query.all()}
    if existing:
        backfilled = 0
        for code, sname in _WT_SALES_NAMES.items():
            if code in existing and not existing[code].sales_name:
                existing[code].sales_name = sname
                backfilled += 1
        if backfilled:
            db.session.commit()
        return
    wht_codes = [
        {'code': 'WC158', 'name': 'Withholding Tax - Goods (Corporation)',    'rate':  1.00},
        {'code': 'WI158', 'name': 'Withholding Tax - Goods (Individual)',     'rate':  1.00},
        {'code': 'WC160', 'name': 'Withholding Tax - Services (Corporation)', 'rate':  2.00},
        {'code': 'WI160', 'name': 'Withholding Tax - Services (Individual)',  'rate':  2.00},
        {'code': 'WC100', 'name': 'Withholding Tax - Rentals (Corporation)',  'rate':  5.00},
        {'code': 'WI100', 'name': 'Withholding Tax - Rentals (Individual)',   'rate':  5.00},
        {'code': 'WC010', 'name': 'Professional Fees (Corporation)',          'rate': 10.00},
        {'code': 'WI010', 'name': 'Professional Fees (Individual)',           'rate':  5.00},
    ]
    for wt in wht_codes:
        db.session.add(WithholdingTax(code=wt['code'], name=wt['name'], description='',
                                      rate=wt['rate'], sales_name=None, is_active=True))
    db.session.commit()
```

- [ ] **Step 4: Rewrite `seed_minimal()` body** to call the helpers (replace the numbered blocks 1-7 between the opening `print(...)` banner and the closing "MINIMAL SEEDING COMPLETE!" banner). The `try/except` wrapper and banners stay:

```python
def seed_minimal():
    """Seed the bare-minimum, general-purpose CORE baseline used by /reset-database.

    (See module docstring for the full inventory: admin/admin123, MAIN branch, 24 settings,
    25 BASELINE_COA accounts, 7 input-VAT / 3 sales-VAT / 8 EWT rows. company_name blank.)
    """
    print("\n" + "="*60)
    print("MINIMAL DATABASE SEEDING")
    print("="*60 + "\n")
    try:
        _seed_admin_and_branch()
        _seed_app_settings('Company Name')
        _seed_accounts(BASELINE_COA)
        _seed_vat_categories()
        _seed_sales_vat_categories()
        _seed_withholding_taxes()
        print("\n" + "="*60)
        print("MINIMAL SEEDING COMPLETE!")
        print("="*60)
        print("\nYou can now log in with:")
        print("  Username: admin")
        print("  Password: admin123")
        print("\n")
    except Exception as e:
        print(f"\n[ERROR] Error during minimal seeding: {str(e)}")
        db.session.rollback()
        raise
```

- [ ] **Step 5: Run the regression test + the manufacturing-COA test**

Run: `pytest tests/unit/test_seed_minimal_regression.py tests/unit/test_manufacturing_coa_types.py -q`
Expected: PASS. If counts differ, the helper extraction dropped/added a row — diff against the pre-refactor block and fix the helper (do not edit the test).

- [ ] **Step 6: Commit**

```bash
git add app/seeds/seed_data.py tests/unit/test_seed_minimal_regression.py
git commit -m "refactor(seeds): extract shared seed helpers; seed_minimal output unchanged"
```

---

### Task 3: `seed_firm()` + `seed-firm` CLI command + integration test

**Files:**
- Modify: `app/seeds/seed_data.py` (add `seed_firm()`; import `FIRM_COA`)
- Modify: `app/__init__.py` (register `seed-firm` CLI command near line 316)
- Test: `tests/unit/test_seed_firm.py`

**Interfaces:**
- Consumes: helpers from Task 2, `FIRM_COA` from Task 1.
- Produces: `seed_firm()` in `seed_data.py`; `seed-firm` Flask CLI command.

- [ ] **Step 1: Write the failing integration test** — `tests/unit/test_seed_firm.py`

```python
from app.seeds.seed_data import seed_firm
from app.seeds.firm_coa import FIRM_COA
from app.accounts.models import Account
from app.settings import AppSettings
from app.vat_categories.models import VATCategory
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax

def test_seed_firm_creates_full_coa(db_session):
    seed_firm()
    assert Account.query.count() == len(FIRM_COA)
    for code in ['10201', '10212', '20101', '20301', '30201', '30301']:
        assert Account.query.filter_by(code=code).first() is not None

def test_seed_firm_sets_placeholder_company_name(db_session):
    seed_firm()
    assert AppSettings.get_setting('company_name') == 'Cruz Accounting & Software'

def test_seed_firm_tax_master_data(db_session):
    seed_firm()
    assert VATCategory.query.count() == 7
    assert SalesVATCategory.query.count() == 3
    assert WithholdingTax.query.count() == 8

def test_seed_firm_vat_pointers_resolve(db_session):
    seed_firm()
    v = VATCategory.query.filter_by(code='V12SV').first()
    assert v.input_vat_account is not None
    assert v.input_vat_account.code == '10503'
    sv = SalesVATCategory.query.filter_by(code='V12').first()
    assert sv.output_vat_account is not None
    assert sv.output_vat_account.code == '20201'

def test_seed_firm_wires_parents(db_session):
    seed_firm()
    ar = Account.query.filter_by(code='10201').first()
    assert ar.parent is not None
    assert ar.parent.code == '10200'

def test_seed_firm_admin_and_branch(db_session):
    seed_firm()
    from app.users.models import User
    from app.branches.models import Branch
    admin = User.query.filter_by(username='admin').first()
    assert admin is not None and admin.role == 'admin'
    assert Branch.query.filter_by(code='MAIN').first() is not None
```

(If `db_session` does not push an app context, wrap each body in `with db_session.app.app_context():` — check `tests/conftest.py` first; the existing seed helpers run inside the fixture's context.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_seed_firm.py -q`
Expected: FAIL — `ImportError: cannot import name 'seed_firm'`

- [ ] **Step 3: Add `seed_firm()`** to `app/seeds/seed_data.py` (place directly below `seed_minimal`), and add the `FIRM_COA` import near the top where `BASELINE_COA` is defined/imported:

```python
from app.seeds.firm_coa import FIRM_COA
```

```python
def seed_firm():
    """Seed a clean combined accounting-firm + software-company instance.

    Same shape as seed_minimal (admin/admin123, MAIN branch, 24 settings, 7/3/8 VAT/EWT)
    but with the FIRM_COA chart of accounts and company_name='Cruz Accounting & Software'.
    """
    print("\n" + "="*60)
    print("FIRM + SOFTWARE DATABASE SEEDING")
    print("="*60 + "\n")
    try:
        _seed_admin_and_branch()
        _seed_app_settings('Cruz Accounting & Software')
        _seed_accounts(FIRM_COA)
        _seed_vat_categories()
        _seed_sales_vat_categories()
        _seed_withholding_taxes()
        print("\n" + "="*60)
        print("FIRM SEEDING COMPLETE!")
        print("="*60)
        print(f"\n  Accounts created: {len(FIRM_COA)}")
        print("  Company: Cruz Accounting & Software (rename in Company Settings)")
        print("  Login -> username: admin  password: admin123 (change after deploy)")
        print("\n")
    except Exception as e:
        print(f"\n[ERROR] Error during firm seeding: {str(e)}")
        db.session.rollback()
        raise
```

- [ ] **Step 4: Register the CLI command** in `app/__init__.py` (immediately after the `seed-minimal` command block, ~line 316):

```python
    @app.cli.command('seed-firm')
    def seed_firm_database():
        """Seed a clean accounting-firm + software-company instance (FIRM_COA + VAT/EWT)."""
        from app.seeds.seed_data import seed_firm
        seed_firm()
```

- [ ] **Step 5: Run the firm tests + the minimal regression test together**

Run: `pytest tests/unit/test_seed_firm.py tests/unit/test_seed_minimal_regression.py tests/unit/test_firm_coa.py -q`
Expected: PASS (all).

- [ ] **Step 6: Verify the CLI command is registered**

Run: `flask seed-firm --help`
Expected: shows the command help line "Seed a clean accounting-firm + software-company instance...". (Do NOT run `flask seed-firm` yet against the dev DB — Task 4 does that against a scratch DB.)

- [ ] **Step 7: Commit**

```bash
git add app/seeds/seed_data.py app/__init__.py tests/unit/test_seed_firm.py
git commit -m "feat(seeds): seed-firm command builds clean firm+software instance"
```

---

### Task 4: Local end-to-end verification (scratch DB)

**Files:** none (verification only). Uses a throwaway DB so the dev `cas.db` is untouched.

- [ ] **Step 1: Seed a scratch DB**

```bash
FLASK_ENV=development SQLALCHEMY_DATABASE_URI="sqlite:///firm_scratch.db" flask db upgrade
FLASK_ENV=development SQLALCHEMY_DATABASE_URI="sqlite:///firm_scratch.db" flask seed-firm
```
Expected: "FIRM SEEDING COMPLETE!" with the account count printed. (On Windows PowerShell use `$env:SQLALCHEMY_DATABASE_URI=...` per line instead of the inline prefix.)

- [ ] **Step 2: Sanity-query the scratch DB**

```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect('instance/firm_scratch.db')  # adjust path if needed
n = c.execute("select count(*) from accounts").fetchone()[0]
magic = ['10201','10212','20101','20301','30201','30301']
present = [r[0] for r in c.execute("select code from accounts where code in (%s)" % ','.join('?'*len(magic)), magic)]
dups = c.execute("select name,count(*) c from accounts group by name having c>1").fetchall()
print("accounts:", n, "| magic present:", sorted(present), "| dup names:", dups)
PY
```
Expected: `accounts:` == len(FIRM_COA), all 6 magic codes present, `dup names: []`.

- [ ] **Step 3: Boot the app on the scratch DB and eyeball the COA**

Launch the dev server pointed at `firm_scratch.db`, log in `admin`/`admin123`, open the Chart of Accounts page. Confirm: groups render as PARENT, leaves postable, Income Statement account picker shows the two revenue groups + cost-of-services split. (Use `/run cas` conventions; point `.env`/URI at the scratch DB, or just verify via the query in Step 2 if a browser boot is inconvenient.)

- [ ] **Step 4: Delete the scratch DB**

```bash
rm -f instance/firm_scratch.db
```

- [ ] **Step 5: No commit** (verification only). Record the confirmed account count in the deploy notes for Task 5.

---

### Task 5: Deploy the clean copy to PythonAnywhere (`alvinccruz`)

**Files:** none in-repo. Executed live via Chrome MCP against `www.pythonanywhere.com`, with the user pasting any interactive step. Prereqs the user supplies at run time: Chrome signed into the `alvinccruz` PA account, a real `SECRET_KEY`, and (optional, for outbound mail) a Gmail app password for `alvinccruz12@gmail.com`.

- [ ] **Step 1: Push CAS to origin** (only after the user says "push")

```bash
git push origin main
```
(The pre-push guard hook runs; if it reports newly-broken modules, STOP and fix before deploying.)

- [ ] **Step 2: PA Bash console — clone/pull the repo**

Open a Bash console in the `alvinccruz` PA account. If first deploy:
```bash
git clone https://github.com/alvin-c-cruz/cas.git ~/cas
```
Else:
```bash
cd ~/cas && git pull origin main
```

- [ ] **Step 3: Build the virtualenv** (rebuild fresh — do not trust a stale `$VIRTUAL_ENV`; the RIC deploy hit an activated-but-deleted venv)

```bash
cd ~/cas
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install python-dateutil    # real runtime dep MISSING from requirements.txt (RIC gotcha)
```

- [ ] **Step 4: Write `.env` on PA** (Files tab or `nano ~/cas/.env`)

```
SECRET_KEY=<the real secret key the user provides>
FLASK_ENV=production
SQLALCHEMY_DATABASE_URI=sqlite:////home/alvinccruz/cas.db
PYTHONANYWHERE_USERNAME=alvinccruz
```
(Add `MAIL_*` settings only if wiring outbound email now.)

- [ ] **Step 5: Build schema + seed the firm COA**

```bash
cd ~/cas && source venv/bin/activate
flask db upgrade
flask seed-firm
```
Expected: "FIRM SEEDING COMPLETE!" with the account count matching Task 4.

- [ ] **Step 6: Configure the Web tab**

- Web app → source code `/home/alvinccruz/cas`, virtualenv `/home/alvinccruz/cas/venv`.
- Edit the WSGI file to import the app from `wsgi.py` and **append `ProxyFix`** to the WSGI application (RIC gotcha — prod HTTPS-enforce infinite-loops without it):
```python
from werkzeug.middleware.proxy_fix import ProxyFix
application.wsgi_app = ProxyFix(application.wsgi_app, x_proto=1, x_host=1)
```

- [ ] **Step 7: Reload + verify**

- Click Reload on the Web tab.
- Navigate to `https://alvinccruz.pythonanywhere.com` — confirm the login page loads over HTTPS (no redirect loop).
- Log in `admin`/`admin123`; open Chart of Accounts (COA renders) and Company Settings (`company_name` = "Cruz Accounting & Software").
- **Change the admin password immediately.**

- [ ] **Step 8: Record the deployment** — note the live URL, DB path, and date; update memory (`project-*` entry) with the new instance identity for future sessions.

---

## Self-Review

**Spec coverage:**
- Build approach (`seed-firm` + `firm_coa.py`, light refactor) → Tasks 1-3. ✓
- Full FIRM_COA with magic codes preserved → Task 1 (data) + Task 1 tests + Task 3 integration. ✓
- VAT/EWT reused verbatim → Task 2 helpers + Task 3 assertions. ✓
- `seed_minimal` unchanged → Task 2 regression test. ✓
- Identity placeholder → `_seed_app_settings('Cruz Accounting & Software')` Task 3, asserted. ✓
- PH tax directions (CWT receivable / WHT payable) → covered by seeded 8 EWT + magic `10212`/`20301`. ✓
- Deploy (PA, ProxyFix, python-dateutil) → Task 5. ✓
- Testing plan items 1-7 from spec → Task 1 static tests + Task 3 integration + Task 2 regression. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code. ✓

**Type consistency:** `FIRM_COA` 6-tuple `(code, name, account_type, classification, normal_balance, parent)` used identically in `firm_coa.py`, all Task 1 tests, and `_seed_accounts` unpacking. Helper names (`_seed_admin_and_branch`, `_seed_app_settings`, `_seed_accounts`, `_seed_vat_categories`, `_seed_sales_vat_categories`, `_seed_withholding_taxes`) match between Task 2 definitions and Task 3 `seed_firm` calls. ✓
