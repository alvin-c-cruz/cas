# Food Toll Packing Demo Dataset — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `flask seed-food-demo` command that builds a contract food-manufacturer demo ("SavorPack Food Manufacturing Corp.") into `cas_demo.db` — Jan 2024 → Jun 2026, single MAIN branch, full periodic RM→WIP→FG→COGS inventory accounting at the GL level — so every CAS report shows realistic, balanced numbers.

**Architecture:** New self-orchestrating module `app/seeds/food_demo.py` that MIRRORS the proven `app/seeds/demo_seed.py` (Zhiyuan) patterns and **imports its company-agnostic builders** (`build_jv`, `build_apv`, `build_crv_collecting`, `build_cdv_paying`, `build_cdv_expense`, `next_doc_number`, `si_number`, `crv_number`, `_money`, `_wht`). Only the food-specific parts are new: the COA (with `classification` set), company/customers/vendors, the finished-goods Sales Invoice builder, and the manufacturing/payroll/depreciation/loan journal vouchers. All money math reuses the real posting helpers so seeded docs are byte-identical to hand-entered ones. Zhiyuan `seed-demo` is untouched.

**Tech Stack:** Flask CLI, SQLAlchemy models, `Decimal` money, the existing `_post_*_je` posting helpers, `app/year_end/service.close_fiscal_year`, pytest (`db_session` fixture).

**Spec:** `docs/superpowers/specs/2026-07-03-food-toll-packing-demo-design.md`

## Global Constraints

- **No app/model/migration changes.** Data generation only. Do NOT edit any `app/**/models.py`, views, or Alembic migrations. New files: `app/seeds/food_demo.py`, the test file, and the CLI block in `app/__init__.py`.
- **`account_type` is the single source of FS placement** — use ONLY the canonical values from `app/accounts/account_types.py`: BS = `Asset`/`Liability`/`Equity`; IS = `Revenue`/`Contra-Revenue`/`Cost of Goods Sold`/`Selling Expense`/`Administrative Expense`/`Other Income`/`Other Expense`/`Income Tax Expense`. A plain `Expense` type appears in NO income-statement section — never use it.
- **Set `classification` (`Current`/`Non-Current`) on every Asset and Liability account** — the Balance Sheet + Cash Flow generators require it. Equity/Revenue/expense accounts leave it `None`.
- **`accounts.name` is UNIQUE** — a parent header and its leaf must have different names (e.g. parent `Cost of Sales`, leaf `Cost of Goods Sold`).
- **Accumulated Depreciation accounts** are `account_type='Asset'` with `normal_balance='credit'` and MUST contain the words "Accumulated Depreciation" in the name (the Cash Flow generator excludes them from Investing by name).
- **Backdated numbering:** never call the built-in `generate_*_number` for document numbers — they key on `datetime.now()`. Use the imported `next_doc_number(prefix, doc_date, counters)` / `si_number(counters)` / `crv_number(counters)` and `build_jv`'s internal `_generate_jv_number(doc_date, branch_id)`, all keyed on the document's own date.
- **Every hand-built JE goes through `build_jv`**, which asserts `is_balanced` and raises `ValueError` if not.
- **Transaction seeders are NOT idempotent.** `run_seed_food_demo(reset=False)` must REFUSE (raise `RuntimeError`) if food transactions already exist, with the rebuild instructions. Rebuild = confirm `.env`→`cas_demo.db` → delete `instance/cas_demo.db` → `flask db upgrade` → `flask seed-food-demo`.
- **Span reaches 2026** (Jan 2024 → Jun 2026) so the app's current-year default filters/dashboard are not empty.
- **Deterministic generation** — vary amounts/mix by loop index (e.g. `(idx * 37 % 11)`), never `random`/`Math.random`/wall-clock, so rebuilds reproduce.
- Admin identity reused: `admin` / `admin123`, branch `MAIN`.

---

## File Structure

- **Create `app/seeds/food_demo.py`** — the entire seeder: `FOOD_COA` data, `COMPANY_SETTINGS`, `WHT_CODES`, `seed_food_coa()`, `seed_food_baseline()`, `seed_food_customers()`, `seed_food_vendors()`, `resolve_food_refs()`, `build_food_si()`, the manufacturing/payroll/depreciation/loan JV generators, `generate_food_transactions()`, and `run_seed_food_demo()`. Imports the generic builders from `app.seeds.demo_seed`.
- **Create `tests/integration/test_food_demo.py`** — per-function tests + full-run balance/refusal/IS-classification acceptance.
- **Modify `app/__init__.py`** — add the `@app.cli.command('seed-food-demo')` block next to the existing `seed-demo` command (~line 335).

Interfaces the tasks share (defined once, used throughout):
- `resolve_food_refs() -> dict` with keys: `cash_on_hand`, `cash_bank` (Account objects); `inv` = `{'rm','wip','fg','pkg'}` → Account; `ppe` = `{'machinery','accum_machinery','vehicles','accum_vehicles','office','accum_office','building','accum_building'}`; `revenue` (40101), `cogs` (50001), `expense` = `{expense_code: Account}` for opex; `accrued_salaries`, `sss`, `phic`, `hdmf`, `wt_comp`, `income_tax_payable`, `loan`, `share_capital`, `interest_expense` → Account.
- `counters` = a plain `dict` threaded through all document builders (holds the per-prefix running sequence; created once in `generate_food_transactions`).
- Reused from `app.seeds.demo_seed` (import, do not redefine): `build_jv(doc_date, lines, refs, admin_id, branch_id, *, entry_type, description, reference='')`, `build_apv(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters)`, `build_crv_collecting(doc_date, invoice, refs, admin_id, branch_id, counters, method='check')`, `build_cdv_paying(doc_date, ap, refs, admin_id, branch_id, counters, method='check')`, `build_cdv_expense(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters, method='cash')`, `next_doc_number`, `si_number`, `crv_number`, `_money`, `_wht`. (`build_apv`/`build_cdv_expense` need `refs['expense'][vendor_spec['expense_code']]` and `vendor_spec` dicts with `'vat'`,`'wht'`,`'expense_code'` — this plan's refs/vendors provide exactly that.)

---

## Task 1: COA builder — `seed_food_coa()` with classification

**Files:** Create `app/seeds/food_demo.py` (start it) · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `seed_food_coa() -> int` (count) and module-level `FOOD_COA` list.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_food_demo.py
from decimal import Decimal
import pytest


def test_seed_food_coa_builds_typed_classified_accounts(db_session):
    from app.seeds.food_demo import seed_food_coa
    from app.accounts.models import Account
    n = seed_food_coa()
    assert n >= 70
    codes = {a.code: a for a in Account.query.all()}
    # New manufacturing accounts exist with the right rich types + classification.
    assert codes['10301'].account_type == 'Asset' and codes['10301'].classification == 'Current'   # Raw Materials
    assert codes['12010'].account_type == 'Asset' and codes['12010'].classification == 'Non-Current' # Machinery
    assert codes['12011'].normal_balance == 'credit'   # Accum Depr (contra-asset)
    assert 'Accumulated Depreciation' in codes['12011'].name
    assert codes['50001'].account_type == 'Cost of Goods Sold'
    assert codes['60101'].account_type == 'Administrative Expense'
    assert codes['61101'].account_type == 'Selling Expense'
    assert codes['70101'].account_type == 'Other Expense'
    assert codes['80101'].account_type == 'Income Tax Expense'
    assert codes['40201'].account_type == 'Other Income'
    # Existing baseline parents preserved.
    assert codes['10100'].name == 'Cash and Cash Equivalents'
    # Year-end close needs these.
    assert '30201' in codes and '30301' in codes
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_food_demo.py::test_seed_food_coa_builds_typed_classified_accounts -v -p no:cacheprovider --no-cov`
Expected: FAIL — `ModuleNotFoundError: app.seeds.food_demo`.

- [ ] **Step 3: Create `app/seeds/food_demo.py` with the COA**

```python
"""SavorPack Food Manufacturing Corp. — contract food-manufacturer demo dataset.
Mirrors demo_seed.py (Zhiyuan) but with a food-manufacturing COA + full periodic
inventory (RM->WIP->FG->COGS) at the GL level. Reuses demo_seed's generic builders.
Span: Jan 2024 -> Jun 2026, single MAIN branch. NOT idempotent (refuses re-run).
"""
from decimal import Decimal
from app import db
from app.accounts.models import Account

# (code, name, account_type, classification, normal_balance, parent_code)
# classification is None for Equity/Revenue/expense; set for every Asset/Liability.
FOOD_COA = [
    # ---- preserve baseline parents + leaves (idempotent add) ----
    ('10100', 'Cash and Cash Equivalents', 'Asset', 'Current', 'debit', None),
    ('10101', 'Cash on Hand', 'Asset', 'Current', 'debit', '10100'),
    ('10110', 'Cash in Bank - Current Account', 'Asset', 'Current', 'debit', '10100'),
    ('10200', 'Trade and Other Receivables', 'Asset', 'Current', 'debit', None),
    ('10201', 'Accounts Receivable - Trade', 'Asset', 'Current', 'debit', '10200'),
    ('10212', 'Creditable Withholding Tax', 'Asset', 'Current', 'debit', '10200'),
    ('10500', 'Input VAT', 'Asset', 'Current', 'debit', None),
    ('10501', 'Input VAT - Capital Goods', 'Asset', 'Current', 'debit', '10500'),
    ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Current', 'debit', '10500'),
    ('10503', 'Input VAT - Services', 'Asset', 'Current', 'debit', '10500'),
    ('10504', 'Input VAT - Importation', 'Asset', 'Current', 'debit', '10500'),
    ('20100', 'Trade and Other Payables', 'Liability', 'Current', 'credit', None),
    ('20101', 'Accounts Payable - Trade', 'Liability', 'Current', 'credit', '20100'),
    ('20200', 'Output VAT', 'Liability', 'Current', 'credit', None),
    ('20201', 'Output VAT - Sales', 'Liability', 'Current', 'credit', '20200'),
    ('20300', 'Withholding and Other Taxes Payable', 'Liability', 'Current', 'credit', None),
    ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Current', 'credit', '20300'),
    ('30200', 'Retained Earnings', 'Equity', None, 'credit', None),
    ('30201', 'Retained Earnings - Unappropriated', 'Equity', None, 'credit', '30200'),
    ('30301', 'Current Year Earnings', 'Equity', None, 'credit', None),
    ('40100', 'Sales', 'Revenue', None, 'credit', None),
    ('40101', 'Sales - Goods', 'Revenue', None, 'credit', '40100'),
    ('40102', 'Sales - Services', 'Revenue', None, 'credit', '40100'),
    # ---- additions ----
    ('10300', 'Inventories', 'Asset', 'Current', 'debit', None),
    ('10301', 'Raw Materials Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10302', 'Work-in-Process Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10303', 'Finished Goods Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10304', 'Packaging Materials Inventory', 'Asset', 'Current', 'debit', '10300'),
    ('10400', 'Prepaid Expenses', 'Asset', 'Current', 'debit', None),
    ('10401', 'Prepaid Insurance', 'Asset', 'Current', 'debit', '10400'),
    ('10402', 'Prepaid Rent', 'Asset', 'Current', 'debit', '10400'),
    ('12000', 'Property, Plant and Equipment', 'Asset', 'Non-Current', 'debit', None),
    ('12010', 'Machinery and Packing Equipment', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12011', 'Accumulated Depreciation - Machinery', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12020', 'Building and Leasehold Improvements', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12021', 'Accumulated Depreciation - Building', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12030', 'Office and Furniture Equipment', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12031', 'Accumulated Depreciation - Office Equipment', 'Asset', 'Non-Current', 'credit', '12000'),
    ('12040', 'Delivery Vehicles', 'Asset', 'Non-Current', 'debit', '12000'),
    ('12041', 'Accumulated Depreciation - Vehicles', 'Asset', 'Non-Current', 'credit', '12000'),
    ('20302', 'Withholding Tax Payable - Compensation', 'Liability', 'Current', 'credit', '20300'),
    ('20400', 'Accrued and Statutory Payables', 'Liability', 'Current', 'credit', None),
    ('20401', 'Accrued Salaries and Wages', 'Liability', 'Current', 'credit', '20400'),
    ('20402', 'SSS Premiums Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20403', 'PhilHealth Contributions Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20404', 'Pag-IBIG Contributions Payable', 'Liability', 'Current', 'credit', '20400'),
    ('20405', 'Accrued Utilities', 'Liability', 'Current', 'credit', '20400'),
    ('20406', 'Income Tax Payable', 'Liability', 'Current', 'credit', '20400'),
    ('25000', 'Loans Payable', 'Liability', 'Non-Current', 'credit', None),
    ('25001', 'Bank Loan Payable', 'Liability', 'Non-Current', 'credit', '25000'),
    ('30100', 'Share Capital', 'Equity', None, 'credit', None),
    ('30101', 'Paid-in Capital', 'Equity', None, 'credit', '30100'),
    ('40200', 'Other Income', 'Other Income', None, 'credit', None),
    ('40201', 'Scrap and By-product Sales', 'Other Income', None, 'credit', '40200'),
    ('40202', 'Interest Income', 'Other Income', None, 'credit', '40200'),
    ('50000', 'Cost of Sales', 'Cost of Goods Sold', None, 'debit', None),
    ('50001', 'Cost of Goods Sold', 'Cost of Goods Sold', None, 'debit', '50000'),
    ('60000', 'Administrative Expenses', 'Administrative Expense', None, 'debit', None),
    ('60101', 'Salaries and Wages - Administrative', 'Administrative Expense', None, 'debit', '60000'),
    ('60102', 'SSS/PhilHealth/Pag-IBIG - Employer Share', 'Administrative Expense', None, 'debit', '60000'),
    ('60103', 'Rent Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('60104', 'Utilities Expense - Office', 'Administrative Expense', None, 'debit', '60000'),
    ('60105', 'Office Supplies', 'Administrative Expense', None, 'debit', '60000'),
    ('60106', 'Repairs and Maintenance', 'Administrative Expense', None, 'debit', '60000'),
    ('60107', 'Depreciation Expense - Administrative', 'Administrative Expense', None, 'debit', '60000'),
    ('60108', 'Professional Fees', 'Administrative Expense', None, 'debit', '60000'),
    ('60109', 'Taxes and Licenses', 'Administrative Expense', None, 'debit', '60000'),
    ('60110', 'Insurance Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('60111', 'Communication Expense', 'Administrative Expense', None, 'debit', '60000'),
    ('61000', 'Selling and Distribution Expenses', 'Selling Expense', None, 'debit', None),
    ('61101', 'Delivery and Freight-out', 'Selling Expense', None, 'debit', '61000'),
    ('61102', 'Fuel and Oil', 'Selling Expense', None, 'debit', '61000'),
    ('61103', 'Advertising and Promotions', 'Selling Expense', None, 'debit', '61000'),
    ('61104', 'Depreciation Expense - Delivery Vehicles', 'Selling Expense', None, 'debit', '61000'),
    ('70000', 'Other Expenses', 'Other Expense', None, 'debit', None),
    ('70101', 'Interest Expense', 'Other Expense', None, 'debit', '70000'),
    ('70102', 'Bank Charges', 'Other Expense', None, 'debit', '70000'),
    ('80000', 'Income Tax Expense', 'Income Tax Expense', None, 'debit', None),
    ('80101', 'Income Tax Expense - Current', 'Income Tax Expense', None, 'debit', '80000'),
]


def seed_food_coa():
    """Two-pass COA build with classification + normal_balance. Idempotent (any-accounts guard)."""
    if Account.query.count() > 0:
        return 0
    by_code = {}
    for code, name, atype, classif, nb, _parent in FOOD_COA:
        acct = Account(code=code, name=name, account_type=atype,
                       classification=classif, normal_balance=nb, is_active=True)
        db.session.add(acct)
        by_code[code] = acct
    db.session.flush()
    for code, _n, _t, _c, _nb, parent in FOOD_COA:
        if parent:
            by_code[code].parent_id = by_code[parent].id
    db.session.commit()
    return len(FOOD_COA)
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_food_demo.py::test_seed_food_coa_builds_typed_classified_accounts -v -p no:cacheprovider --no-cov`
Expected: PASS. If `Account(...)` rejects `classification`/`normal_balance`, re-read `app/accounts/models.py` for the exact column names and adjust the constructor (model-only mismatch, not a design change).

- [ ] **Step 5: Commit**

```bash
git add app/seeds/food_demo.py tests/integration/test_food_demo.py
git commit -m "feat(food-demo): food-manufacturer COA builder with classification"
```

---

## Task 2: Baseline — `seed_food_baseline()`

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `seed_food_baseline() -> {'admin': User, 'branch': Branch}`; module-level `COMPANY_SETTINGS`, `WHT_CODES`.

- [ ] **Step 1: Write the failing test**

```python
def test_seed_food_baseline(db_session):
    from app.seeds.food_demo import seed_food_baseline
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod
    refs0 = seed_food_baseline()
    assert refs0['admin'].username == 'admin'
    assert refs0['branch'].code == 'MAIN'
    assert AppSettings.get_setting('company_name') == 'SavorPack Food Manufacturing Corp.'
    assert VATCategory.query.count() >= 4
    assert SalesVATCategory.query.filter_by(code='V12').first() is not None
    assert WithholdingTax.query.count() >= 3
    # Periods span Jan 2024 -> Jun 2026 (30 months).
    assert AccountingPeriod.query.count() >= 30
    assert AccountingPeriod.query.filter_by(year=2024, month=1).first() is not None
    assert AccountingPeriod.query.filter_by(year=2026, month=6).first() is not None
```

- [ ] **Step 2: Run to verify it fails** — `pytest ...::test_seed_food_baseline` → FAIL (`ImportError: seed_food_baseline`).

- [ ] **Step 3: Add the baseline** (append to `app/seeds/food_demo.py`)

```python
COMPANY_SETTINGS = [
    {'key': 'company_name', 'value': 'SavorPack Food Manufacturing Corp.'},
    {'key': 'company_tin', 'value': '009-888-777-000'},
    {'key': 'company_address', 'value': '12 Riverside Industrial Park, Cabuyao, Laguna'},
    {'key': 'fiscal_year_start', 'value': '01'},
    {'key': 'tin_branch_code', 'value': '000'},
]

# (code, name, rate, sales_name) — sales_name set => usable seller-side; None => purchase-only.
WHT_CODES = [
    {'code': 'WI010', 'name': 'Income payments to suppliers of goods (1%)', 'rate': 1.00,
     'sales_name': 'Sales of goods to top withholding agent (1%)'},
    {'code': 'WI020', 'name': 'Income payments to suppliers of services (2%)', 'rate': 2.00, 'sales_name': None},
    {'code': 'WC160', 'name': 'Rentals (5%)', 'rate': 5.00, 'sales_name': None},
    {'code': 'WC010', 'name': 'Professional fees (10%)', 'rate': 10.00, 'sales_name': None},
]


def seed_food_baseline():
    """Admin, MAIN branch, company settings, tax tables, periods Jan2024->Jun2026. Idempotent."""
    from app.users.models import User
    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod

    seed_food_coa()

    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(username='admin', email='admin@savorpack.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin); db.session.commit()

    branch = Branch.query.filter_by(code='MAIN').first()
    if branch is None:
        branch = Branch(code='MAIN', name='Main Branch', address='Head Office', is_active=True)
        db.session.add(branch); db.session.commit()
    if branch not in admin.branches.all():
        admin.branches.append(branch); db.session.commit()

    if AppSettings.query.count() == 0:
        for s in COMPANY_SETTINGS:
            db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
        db.session.commit()

    if VATCategory.query.count() == 0:
        vat_acct = {a.code: a.id for a in Account.query.filter(
            Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
        for c in [
            {'code': 'VEX', 'name': 'VAT Exempt', 'rate': 0.00, 'acct': None},
            {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'acct': '10501'},
            {'code': 'V12DG', 'name': 'Input Tax Domestic Goods', 'rate': 12.00, 'acct': '10502'},
            {'code': 'V12SV', 'name': 'Input Tax Services', 'rate': 12.00, 'acct': '10503'},
        ]:
            db.session.add(VATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                       description='', is_active=True,
                                       input_vat_account_id=vat_acct.get(c['acct']) if c['acct'] else None))
        db.session.commit()

    if SalesVATCategory.query.count() == 0:
        out_id = Account.query.filter_by(code='20201').first().id
        for c in [
            {'code': 'V12', 'name': 'VATable Sales (12%)', 'rate': 12.00, 'nature': 'regular', 'acct': out_id},
            {'code': 'VEX', 'name': 'VAT-Exempt Sales', 'rate': 0.00, 'nature': 'exempt', 'acct': None},
        ]:
            db.session.add(SalesVATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                            transaction_nature=c['nature'],
                                            output_vat_account_id=c['acct'], is_active=True))
        db.session.commit()

    if WithholdingTax.query.count() == 0:
        for w in WHT_CODES:
            db.session.add(WithholdingTax(code=w['code'], name=w['name'], description='',
                                          rate=w['rate'], sales_name=w['sales_name'], is_active=True))
        db.session.commit()

    py, pm = 2024, 1
    while (py, pm) <= (2026, 6):
        AccountingPeriod.get_or_create_period(py, pm)
        pm += 1
        if pm > 12:
            pm, py = 1, py + 1

    return {'admin': admin, 'branch': branch}
```

- [ ] **Step 4: Run to verify it passes.** If `SalesVATCategory`/`VATCategory`/`WithholdingTax`/`AppSettings.get_setting`/`AccountingPeriod.get_or_create_period` signatures differ, re-check the model (these are copied verbatim from the working `demo_seed.py`, so they should match). Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): baseline (company, tax tables, 2024-2026 periods)"`

---

## Task 3: Customers, vendors, and `resolve_food_refs()`

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `seed_food_customers()`, `seed_food_vendors() -> list[dict]` (vendor specs), `resolve_food_refs() -> dict` (the refs contract in File Structure).

- [ ] **Step 1: Write the failing test**

```python
def test_food_customers_vendors_and_refs(db_session):
    from app.seeds.food_demo import (seed_food_baseline, seed_food_customers,
                                      seed_food_vendors, resolve_food_refs)
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    seed_food_baseline()
    seed_food_customers()
    specs = seed_food_vendors()
    assert Customer.query.count() >= 4
    assert Vendor.query.count() >= 4
    assert all({'vendor', 'vat', 'wht', 'expense_code'} <= set(s) for s in specs)
    refs = resolve_food_refs()
    for k in ('cash_on_hand', 'cash_bank', 'revenue', 'cogs', 'share_capital', 'loan'):
        assert refs[k] is not None
    assert refs['inv']['rm'].code == '10301' and refs['inv']['fg'].code == '10303'
    assert refs['expense']  # non-empty expense map for build_apv/build_cdv_expense
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add customers, vendors, refs** (append to `app/seeds/food_demo.py`)

```python
FOOD_CUSTOMERS = [
    {'code': 'C001', 'name': 'Golden Harvest Foods Inc.', 'vat': 'V12', 'tin': '111-222-333-000'},
    {'code': 'C002', 'name': 'Metro Grocers Corporation', 'vat': 'V12', 'tin': '222-333-444-000'},
    {'code': 'C003', 'name': 'FreshMart Distribution Co.', 'vat': 'V12', 'tin': '333-444-555-000'},
    {'code': 'C004', 'name': 'Island Pantry Trading', 'vat': 'V12', 'tin': '444-555-666-000'},
    {'code': 'C005', 'name': 'SunRise Retail Ventures', 'vat': 'V12', 'tin': '555-666-777-000'},
]

# expense_code = the account each vendor's purchase/expense posts to.
FOOD_VENDORS = [
    {'code': 'V001', 'name': 'AgriSource Raw Materials Inc.', 'tin': '611-000-001-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10301'},   # raw materials -> RM inventory
    {'code': 'V002', 'name': 'PackRight Packaging Supply', 'tin': '611-000-002-000',
     'vat': 'V12DG', 'wht': None, 'expense_code': '10304'},   # packaging -> Pkg inventory
    {'code': 'V003', 'name': 'Laguna Power & Water District', 'tin': '611-000-003-000',
     'vat': 'V12SV', 'wht': None, 'expense_code': '60104'},   # utilities (office)
    {'code': 'V004', 'name': 'RiverPark Realty (Landlord)', 'tin': '611-000-004-000',
     'vat': 'V12SV', 'wht': 'WC160', 'expense_code': '60103'},  # rent (5% EWT)
    {'code': 'V005', 'name': 'Ledesma & Co. CPAs', 'tin': '611-000-005-000',
     'vat': 'V12SV', 'wht': 'WC010', 'expense_code': '60108'},  # professional (10% EWT)
    {'code': 'V006', 'name': 'FastLane Logistics Services', 'tin': '611-000-006-000',
     'vat': 'V12SV', 'wht': 'WI020', 'expense_code': '61101'},  # freight (2% EWT)
]


def seed_food_customers():
    from app.customers.models import Customer
    if Customer.query.count() > 0:
        return 0
    for c in FOOD_CUSTOMERS:
        db.session.add(Customer(code=c['code'], name=c['name'], tin=c['tin'],
                                address='Metro Manila', default_vat_category=c['vat'],
                                is_active=True))
    db.session.commit()
    return len(FOOD_CUSTOMERS)


def seed_food_vendors():
    """Create vendors; return the spec list (with expense_code/vat/wht) for the builders."""
    from app.vendors.models import Vendor
    if Vendor.query.count() == 0:
        for v in FOOD_VENDORS:
            db.session.add(Vendor(code=v['code'], name=v['name'], tin=v['tin'], is_active=True))
        db.session.commit()
    by_code = {v.code: v for v in Vendor.query.all()}
    return [{'vendor': by_code[v['code']], 'vat': v['vat'], 'wht': v['wht'],
             'expense_code': v['expense_code']} for v in FOOD_VENDORS]


def resolve_food_refs():
    """Account-object lookups the transaction builders need."""
    a = {x.code: x for x in Account.query.all()}
    expense_codes = ['60103', '60104', '60105', '60106', '60108', '60109', '60110',
                     '60111', '61101', '61102', '61103', '10301', '10304']
    return {
        'cash_on_hand': a['10101'], 'cash_bank': a['10110'],
        'inv': {'rm': a['10301'], 'wip': a['10302'], 'fg': a['10303'], 'pkg': a['10304']},
        'ppe': {'machinery': a['12010'], 'accum_machinery': a['12011'],
                'building': a['12020'], 'accum_building': a['12021'],
                'office': a['12030'], 'accum_office': a['12031'],
                'vehicles': a['12040'], 'accum_vehicles': a['12041']},
        'revenue': a['40101'], 'cogs': a['50001'],
        'expense': {code: a[code] for code in expense_codes},
        'accrued_salaries': a['20401'], 'sss': a['20402'], 'phic': a['20403'], 'hdmf': a['20404'],
        'wt_comp': a['20302'], 'income_tax_payable': a['20406'],
        'loan': a['25001'], 'share_capital': a['30101'],
        'interest_expense': a['70101'], 'admin_salaries': a['60101'],
        'employer_share': a['60102'], 'admin_depr': a['60107'], 'vehicle_depr': a['61104'],
    }
```

- [ ] **Step 4: Run to verify it passes.** If `Customer`/`Vendor` constructors reject a kwarg, re-check the model (adjust the test-only/constructor field). Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): food customers, vendors, and refs resolver"`

---

## Task 4: Finished-goods Sales Invoice builder — `build_food_si()`

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Consumes `refs`, `counters`. Produces `build_food_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters) -> SalesInvoice` (posted, balanced JE, revenue → 40101, 1% goods EWT via WI010).

- [ ] **Step 1: Write the failing test**

```python
def test_build_food_si_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, seed_food_customers,
                                      resolve_food_refs, build_food_si)
    from app.customers.models import Customer
    r0 = seed_food_baseline(); seed_food_customers()
    refs = resolve_food_refs()
    cust = Customer.query.filter_by(code='C001').first()
    counters = {}
    si = build_food_si(date(2024, 3, 15), cust, Decimal('112000.00'),
                       refs, r0['admin'].id, r0['branch'].id, counters)
    assert si.status == 'posted' and si.journal_entry_id is not None
    je = si.journal_entry
    tot_d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    tot_c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert tot_d == tot_c
    # Revenue line posts to Sales - Goods.
    assert any(l.account_id == refs['revenue'].id for l in je.lines.all())
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the builder** (append to `app/seeds/food_demo.py`)

```python
def build_food_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    """One posted finished-goods Sales Invoice (12% VAT, 1% goods EWT) + balanced posted JE."""
    from datetime import date as _date
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_invoices.views import _post_invoice_je
    from app.utils import ph_now
    from app.seeds.demo_seed import si_number, _money, _wht

    wt = _wht('WI010')  # 1% EWT on goods (seller records buyer's withholding -> CWT)
    si = SalesInvoice(
        branch_id=branch_id, invoice_number=si_number(counters), invoice_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 30),
        customer_id=customer_obj.id, customer_name=customer_obj.name,
        customer_tin=customer_obj.tin, customer_address=customer_obj.address,
        status='posted', amount_paid=Decimal('0.00'),
        created_by_id=admin_id, posted_by_id=admin_id, posted_at=ph_now(),
    )
    item = SalesInvoiceItem(
        line_number=1, description='Packed food products — finished goods',
        amount=_money(gross_amount), vat_category='V12', vat_rate=Decimal('12.00'),
        account_id=refs['revenue'].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()
    si.line_items.append(item)
    si.calculate_totals()
    db.session.add(si); db.session.flush()
    je = _post_invoice_je(si, admin_id)
    si.journal_entry_id = je.id
    db.session.commit()
    return si
```

- [ ] **Step 4: Run to verify it passes.** If `_wht('WI010')` returns None (code mismatch), confirm Task 2's `WHT_CODES` includes `WI010`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): finished-goods sales invoice builder"`

---

## Task 5: Opening capitalization JV — `build_food_opening()`

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `build_food_opening(refs, admin_id, branch_id) -> JournalEntry` — the 2024-01-01 launch entry via the imported `build_jv`.

- [ ] **Step 1: Write the failing test**

```python
def test_build_food_opening_balances(db_session):
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs, build_food_opening)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    je = build_food_opening(refs, r0['admin'].id, r0['branch'].id)
    assert je.is_balanced
    from datetime import date
    assert je.entry_date == date(2024, 1, 1)
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the opening builder** (append)

```python
def build_food_opening(refs, admin_id, branch_id):
    """2024-01-01 launch: capital + bank loan fund cash, equipment, and opening raw materials."""
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv
    lines = [
        (refs['cash_bank'], Decimal('3000000.00'), Decimal('0.00')),
        (refs['ppe']['machinery'], Decimal('4000000.00'), Decimal('0.00')),
        (refs['ppe']['building'], Decimal('2500000.00'), Decimal('0.00')),
        (refs['ppe']['vehicles'], Decimal('1200000.00'), Decimal('0.00')),
        (refs['ppe']['office'], Decimal('300000.00'), Decimal('0.00')),
        (refs['inv']['rm'], Decimal('800000.00'), Decimal('0.00')),
        (refs['inv']['pkg'], Decimal('200000.00'), Decimal('0.00')),
        # Debits total 12,000,000 (3M+4M+2.5M+1.2M+0.3M+0.8M+0.2M) = funded 6M capital + 6M loan.
        (refs['share_capital'], Decimal('0.00'), Decimal('6000000.00')),
        (refs['loan'], Decimal('0.00'), Decimal('6000000.00')),
    ]
    return build_jv(date(2024, 1, 1), lines, refs, admin_id, branch_id,
                    entry_type='opening_balance', description='Opening balances — company launch',
                    reference='OPENING BALANCES')
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS (is_balanced True; debits 12,000,000 == credits 12,000,000).

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): opening capitalization journal voucher"`

---

## Task 6: Manufacturing JVs — production, WIP, COGS

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `build_production_jv(doc_date, amount, refs, admin_id, branch_id)`, `build_cogs_jv(doc_date, amount, refs, admin_id, branch_id)` — both return `JournalEntry` via `build_jv`.

- [ ] **Step 1: Write the failing test**

```python
def test_manufacturing_jvs_balance_and_move_inventory(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs,
                                      build_food_opening, build_production_jv, build_cogs_jv)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    build_food_opening(refs, r0['admin'].id, r0['branch'].id)
    p = build_production_jv(date(2024, 2, 29), Decimal('500000.00'), refs, r0['admin'].id, r0['branch'].id)
    c = build_cogs_jv(date(2024, 2, 29), Decimal('420000.00'), refs, r0['admin'].id, r0['branch'].id)
    assert p.is_balanced and c.is_balanced
    # Production debits Finished Goods; COGS credits Finished Goods.
    assert any(l.account_id == refs['inv']['fg'].id and l.debit_amount > 0 for l in p.lines.all())
    assert any(l.account_id == refs['inv']['fg'].id and l.credit_amount > 0 for l in c.lines.all())
    assert any(l.account_id == refs['cogs'].id and l.debit_amount > 0 for l in c.lines.all())
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the manufacturing builders** (append)

```python
def build_production_jv(doc_date, amount, refs, admin_id, branch_id):
    """Capitalize a month's factory costs into Finished Goods: RM + labor + factory depreciation.
    amount = total finished-goods value produced this period; split into cost components."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    amt = _money(amount)
    rm = _money(amount * Decimal('0.55'))          # raw materials consumed
    labor = _money(amount * Decimal('0.25'))       # factory direct labor (accrued)
    depr = _money(amount - rm - labor)             # factory machine depreciation (residual balancer)
    # Capitalize factory costs straight into Finished Goods (simple monthly full-completion model;
    # WIP is exercised separately by the orchestrator's optional partial-completion entry).
    lines = [
        (refs['inv']['fg'], amt, Decimal('0.00')),
        (refs['inv']['rm'], Decimal('0.00'), rm),
        (refs['accrued_salaries'], Decimal('0.00'), labor),
        (refs['ppe']['accum_machinery'], Decimal('0.00'), depr),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='reclassification', description='Production — finished goods completed')


def build_cogs_jv(doc_date, amount, refs, admin_id, branch_id):
    """Recognize cost of goods sold for the period: Finished Goods -> COGS."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    amt = _money(amount)
    lines = [
        (refs['cogs'], amt, Decimal('0.00')),
        (refs['inv']['fg'], Decimal('0.00'), amt),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='reclassification', description='Cost of goods sold — period')
```

> Note: delete the dead placeholder `lines = [...]` first assignment shown above — keep only the second, real `lines`. (It's shown only to make the intent explicit; the final code has ONE `lines`.)

- [ ] **Step 4: Run to verify it passes.** Expected: PASS (both balanced; FG moves in on production, out on COGS).

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): production + COGS journal vouchers"`

---

## Task 7: Payroll, depreciation, and loan JVs

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `build_payroll_jv(doc_date, gross, refs, admin_id, branch_id)`, `build_depreciation_jv(doc_date, refs, admin_id, branch_id)`, `build_loan_amort_jv(doc_date, principal, interest, refs, admin_id, branch_id)` — each returns a balanced `JournalEntry`.

- [ ] **Step 1: Write the failing test**

```python
def test_payroll_depr_loan_jvs_balance(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, resolve_food_refs,
                                      build_payroll_jv, build_depreciation_jv, build_loan_amort_jv)
    r0 = seed_food_baseline(); refs = resolve_food_refs()
    a = r0['admin'].id; b = r0['branch'].id
    assert build_payroll_jv(date(2024, 1, 31), Decimal('250000.00'), refs, a, b).is_balanced
    assert build_depreciation_jv(date(2024, 1, 31), refs, a, b).is_balanced
    assert build_loan_amort_jv(date(2024, 1, 31), Decimal('100000.00'), Decimal('50000.00'), refs, a, b).is_balanced
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the builders** (append)

```python
def build_payroll_jv(doc_date, gross, refs, admin_id, branch_id):
    """Admin salaries + statutory + WT-compensation accrual (net settled later via CDV)."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    gross = _money(gross)
    sss = _money(gross * Decimal('0.045'))
    phic = _money(gross * Decimal('0.02'))
    hdmf = _money(Decimal('100.00'))
    wtx = _money(gross * Decimal('0.08'))
    employer = _money(gross * Decimal('0.09'))
    net = _money(gross - sss - phic - hdmf - wtx)
    lines = [
        (refs['admin_salaries'], gross, Decimal('0.00')),
        (refs['employer_share'], employer, Decimal('0.00')),
        (refs['sss'], Decimal('0.00'), _money(sss + employer * Decimal('0.6'))),
        (refs['phic'], Decimal('0.00'), _money(phic + employer * Decimal('0.3'))),
        (refs['hdmf'], Decimal('0.00'), _money(hdmf + employer * Decimal('0.1'))),
        (refs['wt_comp'], Decimal('0.00'), wtx),
        (refs['accrued_salaries'], Decimal('0.00'), net),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='adjustment', description='Payroll accrual — administrative')


def build_depreciation_jv(doc_date, refs, admin_id, branch_id):
    """Monthly admin (office) + selling (vehicle) depreciation. Factory depr is in production."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    office = _money(Decimal('300000.00') / 60)     # 5-yr straight line
    vehicle = _money(Decimal('1200000.00') / 60)
    lines = [
        (refs['admin_depr'], office, Decimal('0.00')),
        (refs['vehicle_depr'], vehicle, Decimal('0.00')),
        (refs['ppe']['accum_office'], Decimal('0.00'), office),
        (refs['ppe']['accum_vehicles'], Decimal('0.00'), vehicle),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='adjustment', description='Depreciation — admin and delivery')


def build_loan_amort_jv(doc_date, principal, interest, refs, admin_id, branch_id):
    """Monthly bank-loan amortization: principal + interest paid from bank."""
    from decimal import Decimal
    from app.seeds.demo_seed import build_jv, _money
    principal = _money(principal); interest = _money(interest)
    lines = [
        (refs['loan'], principal, Decimal('0.00')),
        (refs['interest_expense'], interest, Decimal('0.00')),
        (refs['cash_bank'], Decimal('0.00'), _money(principal + interest)),
    ]
    return build_jv(doc_date, lines, refs, admin_id, branch_id,
                    entry_type='adjustment', description='Bank loan amortization')
```

- [ ] **Step 4: Run to verify it passes.** If a payroll split doesn't tie exactly (rounding), adjust the `accrued_salaries` net line to be the balancer: `net = gross + employer - (sss+phic+hdmf lines) - wtx`. The `build_jv` guard will catch any imbalance — make the last credit the residual. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): payroll, depreciation, and loan-amortization JVs"`

---

## Task 8: Transaction orchestrator — `generate_food_transactions()`

**Files:** Modify `app/seeds/food_demo.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Consumes all builders + reused `build_apv`/`build_crv_collecting`/`build_cdv_paying`/`build_cdv_expense`. Produces `generate_food_transactions(refs, admin_id, branch_id) -> summary dict` with keys `si, ap, crv, cdv, jv, unbalanced` (ints). Iterates months Jan 2024 → Jun 2026 deterministically.

- [ ] **Step 1: Write the failing test**

```python
def test_generate_food_transactions_counts_and_balance(db_session):
    from decimal import Decimal
    from app.seeds.food_demo import (seed_food_baseline, seed_food_customers,
                                      seed_food_vendors, resolve_food_refs, generate_food_transactions)
    from app.journal_entries.models import JournalEntry
    r0 = seed_food_baseline(); seed_food_customers(); seed_food_vendors()
    refs = resolve_food_refs()
    summary = generate_food_transactions(refs, r0['admin'].id, r0['branch'].id)
    assert summary['si'] >= 100 and summary['ap'] >= 100 and summary['jv'] >= 60
    assert summary['unbalanced'] == 0
    tot_d = tot_c = Decimal('0')
    for je in JournalEntry.query.filter_by(status='posted').all():
        tot_d += sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
        tot_c += sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert tot_d == tot_c
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the orchestrator** (append). Iterate months, drive builders with index-varied amounts; collect the opening + monthly JVs and per-month SI/AP + settlements; count and detect unbalanced.

```python
def generate_food_transactions(refs, admin_id, branch_id):
    from datetime import date
    from decimal import Decimal
    from calendar import monthrange
    from app.journal_entries.models import JournalEntry
    from app.customers.models import Customer
    from app.seeds.demo_seed import (build_apv, build_crv_collecting, build_cdv_paying,
                                      build_cdv_expense, _money)

    counters = {}
    summary = {'si': 0, 'ap': 0, 'crv': 0, 'cdv': 0, 'jv': 0, 'unbalanced': 0}

    build_food_opening(refs, admin_id, branch_id); summary['jv'] += 1

    customers = Customer.query.order_by(Customer.code).all()
    vendor_specs = seed_food_vendors()  # returns spec list; vendors already exist
    rm_vendors = [s for s in vendor_specs if s['expense_code'] in ('10301', '10304')]
    opex_vendors = [s for s in vendor_specs if s['expense_code'] not in ('10301', '10304')]

    y, m = 2024, 1
    idx = 0
    while (y, m) <= (2026, 6):
        last = monthrange(y, m)[1]
        eom = date(y, m, last)
        n_sales = 8 + (idx * 37) % 8          # 8..15
        n_purch = 10 + (idx * 53) % 8         # 10..17

        # Sales + collections
        for k in range(n_sales):
            cust = customers[(idx + k) % len(customers)]
            gross = _money(Decimal('80000') + Decimal(str(((idx + k) * 6131) % 90000)))
            si = build_food_si(date(y, m, 1 + (k * 2) % last), cust, gross,
                               refs, admin_id, branch_id, counters); summary['si'] += 1
            if k % 5 != 0:  # ~80% collected within the period -> aging spread
                build_crv_collecting(date(y, m, min(last, 20 + k % 8)), si, refs,
                                     admin_id, branch_id, counters); summary['crv'] += 1

        # Raw-material / packaging purchases + payments
        for k in range(n_purch):
            spec = rm_vendors[(idx + k) % len(rm_vendors)]
            gross = _money(Decimal('40000') + Decimal(str(((idx + k) * 4211) % 60000)))
            ap = build_apv(date(y, m, 2 + (k * 2) % (last - 1)), spec['vendor'], spec, gross,
                           refs, admin_id, branch_id, counters); summary['ap'] += 1
            if k % 4 != 0:
                build_cdv_paying(date(y, m, min(last, 22 + k % 6)), ap, refs,
                                 admin_id, branch_id, counters); summary['cdv'] += 1

        # Monthly opex (rent, utilities, professional, freight) via direct CDV expense
        for spec in opex_vendors:
            gross = _money(Decimal('15000') + Decimal(str((idx * 977) % 40000)))
            build_cdv_expense(eom, spec['vendor'], spec, gross, refs,
                              admin_id, branch_id, counters); summary['cdv'] += 1

        # Manufacturing + payroll + depreciation + loan (month-end JVs)
        produced = _money(Decimal('600000') + Decimal(str((idx * 8123) % 300000)))
        sold = _money(produced * Decimal('0.85'))
        build_production_jv(eom, produced, refs, admin_id, branch_id); summary['jv'] += 1
        build_cogs_jv(eom, sold, refs, admin_id, branch_id); summary['jv'] += 1
        build_payroll_jv(eom, _money(Decimal('280000')), refs, admin_id, branch_id); summary['jv'] += 1
        build_depreciation_jv(eom, refs, admin_id, branch_id); summary['jv'] += 1
        build_loan_amort_jv(eom, _money(Decimal('100000')), _money(Decimal('40000')),
                            refs, admin_id, branch_id); summary['jv'] += 1

        idx += 1
        m += 1
        if m > 12:
            m, y = 1, y + 1

    summary['unbalanced'] = JournalEntry.query.filter_by(status='posted', is_balanced=False).count()
    return summary
```

- [ ] **Step 4: Run to verify it passes.** This runs the full 30-month generation (slow — allow a couple minutes). If `unbalanced > 0`, the offending builder's `build_jv` would already have raised; if the *count* assertion is short, widen the per-month `n_sales`/`n_purch`. Expected: PASS, `unbalanced == 0`, total debits == total credits.

- [ ] **Step 5: Commit** — `git commit -m "feat(food-demo): 30-month transaction orchestrator"`

---

## Task 9: `run_seed_food_demo()` + year-end close + CLI command

**Files:** Modify `app/seeds/food_demo.py` · Modify `app/__init__.py` · Test `tests/integration/test_food_demo.py`

**Interfaces:** Produces `run_seed_food_demo(reset=False) -> summary dict`; the `flask seed-food-demo` command.

- [ ] **Step 1: Write the failing tests** (full-run balance, refuse-on-rerun, IS classifies, BS balances)

```python
def test_run_seed_food_demo_full(db_session):
    from decimal import Decimal
    from datetime import date
    from app.seeds.food_demo import run_seed_food_demo
    from app.reports.financial import generate_income_statement, generate_balance_sheet
    s = run_seed_food_demo(reset=False)
    assert s['unbalanced'] == 0 and s['si'] >= 100
    # Income Statement classifies via rich account_types.
    is_ = generate_income_statement(date(2025, 1, 1), date(2025, 12, 31), branch_id=None)
    assert is_['net_income'] is not None
    # Balance Sheet balances.
    bs = generate_balance_sheet(date(2025, 12, 31), branch_id=None)
    assert abs(bs['total_assets'] - (bs['total_liabilities'] + bs['total_equity'])) < 0.01


def test_run_seed_food_demo_refuses_double_run(db_session):
    import pytest
    from app.seeds.food_demo import run_seed_food_demo
    run_seed_food_demo(reset=False)
    with pytest.raises(RuntimeError):
        run_seed_food_demo(reset=False)
```

> Verify `generate_income_statement` / `generate_balance_sheet` signatures + return keys (`net_income`, `total_assets`, `total_liabilities`, `total_equity`) against `app/reports/financial.py` before finalizing — adjust the assertion keys to the real ones if they differ.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Add the orchestrator + year-end** (append to `food_demo.py`)

```python
def run_seed_food_demo(reset=False):
    """Reset (optional), build baseline + masters + 30 months of transactions, close 2024/2025."""
    if reset:
        db.drop_all(); db.create_all()
    r0 = seed_food_baseline()
    seed_food_customers()
    seed_food_vendors()
    refs = resolve_food_refs()
    from app.sales_invoices.models import SalesInvoice
    if not reset and SalesInvoice.query.count() > 0:
        raise RuntimeError(
            "Food-demo transactions already present in this database. "
            "To rebuild: delete the DB file, run `flask db upgrade`, then `flask seed-food-demo`. "
            "(Refusing to add duplicates — invoice/AP numbers are unique.)")
    summary = generate_food_transactions(refs, r0['admin'].id, r0['branch'].id)
    # Close the two complete fiscal years so Retained Earnings rolls; 2026 stays open.
    from app.year_end.service import close_fiscal_year
    close_fiscal_year(2024, r0['admin'].id)
    close_fiscal_year(2025, r0['admin'].id)
    return summary
```

- [ ] **Step 4: Add the CLI command** in `app/__init__.py`, immediately after the existing `seed-demo` block (~line 335):

```python
    @app.cli.command('seed-food-demo')
    def seed_food_demo_command():
        """Build the SavorPack Food Manufacturing demo dataset into the active DB."""
        from app.seeds.food_demo import run_seed_food_demo
        summary = run_seed_food_demo(reset=False)
        print("\n[OK] Food demo seed complete:")
        for k in ('si', 'ap', 'crv', 'cdv', 'jv', 'unbalanced'):
            print(f"  {k:>12}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")
```

- [ ] **Step 5: Run to verify it passes.** `pytest tests/integration/test_food_demo.py -m '' -p no:cacheprovider --no-cov` (the whole file). If `close_fiscal_year` raises (e.g. a draft in-year, or net-income reconciliation mismatch), read `app/year_end/service.py::assert_closeable` — all seeded docs are `status='posted'`, so drafts shouldn't exist; a reconciliation mismatch means an expense/revenue account_type is wrong (fix the COA type, not the close). Expected: all tests PASS.

- [ ] **Step 6: Commit** — `git commit -m "feat(food-demo): run_seed_food_demo + year-end close + flask seed-food-demo command"`

---

## Task 10: Live browser verification (the past-year-invisible gotcha)

**Files:** none (verification only) — plus a short note appended to the spec's testing section if anything is off.

pytest passes on date-agnostic data that no default page shows. Verify the running app under DEFAULT (2026) filters.

- [ ] **Step 1: Build into the dev DB.** Confirm `.env` → `sqlite:///cas_demo.db`, then:
```bash
rm -f instance/cas_demo.db
venv/Scripts/python -m flask db upgrade
venv/Scripts/python -m flask seed-food-demo
```
Expected: prints non-zero `si/ap/crv/cdv/jv` and `unbalanced: 0`.

- [ ] **Step 2: Restart the dev server** (`.py`/DB change) and log in (`admin`/`admin123`).

- [ ] **Step 3: Spot-check under default filters** — Dashboard shows current-year revenue/expense/AR/AP; `/sales-invoices` and `/accounts-payable` lists show 2026 rows; `/reports/trial-balance` (as-of today) is balanced; `/reports/income-statement` (2026 YTD) shows Sales, Cost of Goods Sold, Gross Profit, Admin/Selling expenses, Operating Income; `/reports/balance-sheet` shows Inventories + PPE (net of accumulated depreciation) and **balances**; `/reports/cash-flow` reconciles.

- [ ] **Step 4: Commit** any spec note (only if a discrepancy was found and documented) — otherwise nothing to commit.

---

## Self-Review

**1. Spec coverage:**
- Company identity + span (2024+2025+2026-YTD) → Tasks 2, 8. ✓
- COA preserve-baseline + additions with rich `account_type`/`classification` → Task 1. ✓
- VAT/SalesVAT/WHT wired → Task 2. ✓
- Opening balances → Task 5. ✓
- Purchase cycle (AP/CDV, Input VAT, WHT on services) → reused `build_apv`/`build_cdv_paying`/`build_cdv_expense` driven in Task 8. ✓
- Production/WIP/COGS periodic → Task 6 + Task 8. ✓
- Sales cycle (SI + output VAT + 1% EWT) + collections → Task 4 + Task 8. ✓
- Payroll, depreciation, loan/interest → Task 7 + Task 8. ✓
- Year-end close 2024/2025 → Task 9. ✓
- Reuse real posting helpers; date-keyed numbering; is_balanced guards; refuse-on-rerun → Tasks 4–9 (imports from demo_seed; `run_seed_food_demo` guard). ✓
- CLI command → Task 9. ✓
- Testing (TB/BS balance, no unbalanced, IS classifies, refuse-on-rerun) + browser check → Tasks 8, 9, 10. ✓
- No app/model/migration changes → all tasks touch only `app/seeds/food_demo.py`, the test, and the `app/__init__.py` CLI block. ✓

**2. Placeholder scan:** none. The opening JV (Task 5) is pre-balanced (12M debits = 6M capital + 6M loan) and the production JV (Task 6) has a single clean `lines` set. No `TBD`/"add error handling"/"similar to Task N"/dead-placeholder code remains.

**3. Type/name consistency:** `refs` keys (`inv.{rm,wip,fg,pkg}`, `ppe.{machinery,accum_machinery,...}`, `expense`, `cogs`, `revenue`, `accrued_salaries`, `wt_comp`, `income_tax_payable`, `loan`, `share_capital`, `interest_expense`, `admin_salaries`, `employer_share`, `admin_depr`, `vehicle_depr`) are defined in Task 3 and used identically in Tasks 4–8. `counters` is a plain dict threaded through all builders. `summary` keys (`si,ap,crv,cdv,jv,unbalanced`) match the CLI loop in Task 9. Reused demo_seed signatures match the extracted reference. ✓
