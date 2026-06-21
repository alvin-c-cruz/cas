# CAS Demo Database (Zhiyuan Construction Corporation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible `flask seed-demo` command that populates a construction-company demo database (COA, master data, and ~50–58 posted SI/CR/AP/CD/JV documents for Jan 1 – Jun 19 2025, incl. stockholder investments).

**Architecture:** One new module `app/seeds/demo_seed.py`, modelled directly on the existing `app/seeds/history_seed.py`. It builds documents and posts them through the real `_post_*_je()` helpers so every journal entry balances exactly like a hand-entered voucher. A `seed-demo` CLI command (registered in `app/__init__.py`) orchestrates baseline → master data → transactions. Idempotent (skip-by-code / skip-by-number) so it can build a clean DB or top up the DB that holds the UI validation samples.

**Tech Stack:** Flask CLI (`@app.cli.command`), SQLAlchemy, Python `random.Random` (fixed seed for determinism), `Decimal` (ROUND_HALF_UP), pytest integration tests.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-21-cas-demo-database-design.md`. Related: `docs/superpowers/specs/2026-06-21-ric-cas-database-separation-design.md`.
- **Reuse posting helpers, never re-implement GL math.** `_post_invoice_je(invoice, user_id)`, `_post_ap_je(ap, user_id)`, `_post_crv_je(crv, user_id)`, `_post_cdv_je(cdv, user_id)` all **add+flush but DO NOT commit** — the caller sets `doc.journal_entry_id = je.id` and commits. The created JE's status mirrors the document's status at call time (posted doc → posted JE).
- **Magic account codes the posting code requires (must exist, active, postable/leaf):** `10201` AR-Trade, `10212` Creditable WHT Receivable, `10501–10504` Input VAT, `20101` AP-Trade, `20301` WHT Payable-Expanded, `20401` Output VAT Payable.
- **Backdated numbering:** the built-in generators (`generate_ap_number()`, etc.) sequence on *today's* month, so they cannot produce 2025-dated numbers. Use a local `next_doc_number(prefix, doc_date, counters)` keyed on the document date (same approach as `history_seed.py`). SI/CRV numbers are plain 5-digit continuous (`f'{n:05d}'`).
- **Periods:** posting requires an open `AccountingPeriod`. Call `AccountingPeriod.get_or_create_period(year, month)` for 2025 months 1–6 (created `status='open'`).
- **Audit:** in batch context there is no `current_user`; pass `user_id=admin_id` to `log_audit(...)` where used (the posting helpers handle their own; generators need not call it).
- **Account model:** `Account(code, name, account_type, normal_balance, is_active, parent_id)`. `account_type` ∈ {`Asset`,`Liability`,`Equity`,`Revenue`,`Expense`} (case-sensitive). No stored `is_header` — hierarchy derived from `parent_id`.
- **Customer/Vendor WHT:** many-to-many `.withholding_taxes` (list of `WithholdingTax`). `default_vat_category` is a string code. Customer also has legacy `default_wt_code` (string).
- **Tax codes:** VAT (input) `V12CG/V12DG/V12SV/V12IM` (12%, →10501-10504), `V0/VEX/INV` (0%). Sales VAT (output) `V12` (12%, →20401), `V0`, `VEX`. WHT `WC120` Contractors 2%, `WC158` Goods 1%, `WC160` Services 2%, `WC100` Rentals 5%, `WC010` Professional 10%.
- **Determinism:** all randomness via one `random.Random(20250101)`; no `datetime.now()` for amounts/dates inside generators (end date is passed in).
- **Tests:** every CRUD/post test asserts the linked JE is balanced + `status='posted'`, and (per CLAUDE.md) verifies side effects (CRV reduces SI balance, CDV reduces AP balance).

---

## File Structure

- **Create:** `app/seeds/demo_seed.py` — the entire demo generator (constants + functions). One cohesive file, mirroring `app/seeds/history_seed.py`.
- **Modify:** `app/__init__.py` (~line 289, after the `seed-history` registration) — add the `seed-demo` CLI command.
- **Create:** `tests/integration/test_demo_seed.py` — integration tests for every unit.
- **Modify:** `app/seeds/seed_data.py` — small cleanup only (Task 12), no behavior change to `seed-db`/`seed-minimal`.

Read `app/seeds/history_seed.py` first — it is the canonical pattern for every generator here.

---

### Task 1: Construction Chart of Accounts

**Files:**
- Create: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Produces: `CONSTRUCTION_COA` (list of dicts), `seed_construction_coa() -> int` (count created; idempotent, returns 0 if accounts already exist).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_demo_seed.py
from app.accounts.models import Account


def test_seed_construction_coa_creates_magic_codes(db_session):
    from app.seeds.demo_seed import seed_construction_coa
    n = seed_construction_coa()
    assert n >= 55
    # Magic codes the posting engine hardcodes must exist, be active, and be leaf (postable).
    for code in ['10201', '10212', '10501', '10502', '10503', '10504',
                 '20101', '20301', '20401']:
        a = Account.query.filter_by(code=code).first()
        assert a is not None, f'missing magic account {code}'
        assert a.is_active is True
        assert len(a.children) == 0, f'{code} must be a postable leaf'
    # Construction-specific accounts present
    assert Account.query.filter_by(code='40101').first().name == 'Construction Contract Revenue'
    assert Account.query.filter_by(code='10310').first() is not None  # CIP
    # Idempotent
    assert seed_construction_coa() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_construction_coa_creates_magic_codes -v`
Expected: FAIL — `ModuleNotFoundError: app.seeds.demo_seed`.

- [ ] **Step 3: Write minimal implementation**

```python
# app/seeds/demo_seed.py
"""CAS demo-data generator — Zhiyuan Construction Corporation.

Builds documents and posts them through the real posting helpers so every
journal entry balances exactly like a hand-entered voucher. Mirrors
app/seeds/history_seed.py. See
docs/superpowers/specs/2026-06-21-cas-demo-database-design.md.
"""
import calendar
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account

TWO = Decimal('0.01')


def _money(x):
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


# code, name, type, parent, normal_balance
CONSTRUCTION_COA = [
    # ---- ASSETS ----
    {'code': '10000', 'name': 'CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'nb': 'debit'},
    {'code': '10101', 'name': 'Cash on Hand', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10102', 'name': 'Petty Cash Fund', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10111', 'name': 'Cash in Bank - Current Account', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10112', 'name': 'Cash in Bank - Savings Account', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10201', 'name': 'Accounts Receivable - Trade', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10203', 'name': 'Retention Receivable', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10210', 'name': 'Advances to Subcontractors/Suppliers', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10212', 'name': 'Creditable Withholding Tax Receivable', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10301', 'name': 'Construction Materials Inventory', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10310', 'name': 'Construction in Progress (CIP)', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10500', 'name': 'Input VAT', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10501', 'name': 'Input VAT - Capital Goods', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10502', 'name': 'Input VAT - Domestic Goods', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10503', 'name': 'Input VAT - Services', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10504', 'name': 'Input VAT - Importation', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '11000', 'name': 'NON-CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'nb': 'debit'},
    {'code': '11110', 'name': 'Construction Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11111', 'name': 'Accumulated Depreciation - Construction Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11120', 'name': 'Vehicles', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11121', 'name': 'Accumulated Depreciation - Vehicles', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11130', 'name': 'Tools and Small Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11131', 'name': 'Accumulated Depreciation - Tools and Small Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11140', 'name': 'Office Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11141', 'name': 'Accumulated Depreciation - Office Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    # ---- LIABILITIES ----
    {'code': '20000', 'name': 'CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'nb': 'credit'},
    {'code': '20101', 'name': 'Accounts Payable - Trade', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20110', 'name': 'Subcontractors Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20120', 'name': 'Retention Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20300', 'name': 'Withholding Tax Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20301', 'name': 'Withholding Tax Payable - Expanded', 'type': 'Liability', 'parent': '20300', 'nb': 'credit'},
    {'code': '20302', 'name': 'Withholding Tax Payable - Compensation', 'type': 'Liability', 'parent': '20300', 'nb': 'credit'},
    {'code': '20401', 'name': 'Output VAT Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20420', 'name': 'Statutory Payables', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20421', 'name': 'SSS Premiums Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20422', 'name': 'PhilHealth Contributions Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20423', 'name': 'Pag-IBIG Contributions Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20430', 'name': 'Billings in Excess of Costs', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '21000', 'name': 'NON-CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'nb': 'credit'},
    {'code': '21101', 'name': 'Loans Payable', 'type': 'Liability', 'parent': '21000', 'nb': 'credit'},
    # ---- EQUITY ----
    {'code': '30000', 'name': 'EQUITY', 'type': 'Equity', 'parent': None, 'nb': 'credit'},
    {'code': '30101', 'name': 'Capital Stock', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30102', 'name': 'Additional Paid-in Capital', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30103', 'name': 'Subscriptions Receivable', 'type': 'Equity', 'parent': '30000', 'nb': 'debit'},
    {'code': '30201', 'name': 'Retained Earnings', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30301', 'name': 'Current-Year Earnings', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    # ---- REVENUE ----
    {'code': '40000', 'name': 'REVENUE', 'type': 'Revenue', 'parent': None, 'nb': 'credit'},
    {'code': '40101', 'name': 'Construction Contract Revenue', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40102', 'name': 'Service Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40103', 'name': 'Materials Sales', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40201', 'name': 'Equipment Rental Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40202', 'name': 'Interest Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40203', 'name': 'Miscellaneous Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    # ---- COST OF CONSTRUCTION ----
    {'code': '50100', 'name': 'Cost of Construction', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50101', 'name': 'Direct Materials', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50102', 'name': 'Direct Labor', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50103', 'name': 'Subcontractor Costs', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50104', 'name': 'Equipment Rental Expense', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50105', 'name': 'Permits and Project Fees', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50106', 'name': 'Project Overhead', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    # ---- OPERATING EXPENSES ----
    {'code': '50200', 'name': 'Operating Expenses', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50210', 'name': 'Salaries and Wages', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50211', 'name': 'Employee Benefits', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50220', 'name': 'Rent Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50221', 'name': 'Utilities - Electricity', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50222', 'name': 'Utilities - Water', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50223', 'name': 'Communications', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50230', 'name': 'Office Supplies Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50240', 'name': 'Professional Fees', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50250', 'name': 'Taxes and Licenses', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50260', 'name': 'Depreciation Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50270', 'name': 'Repairs and Maintenance', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50280', 'name': 'Fuel and Oil', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50290', 'name': 'Representation and Entertainment', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50298', 'name': 'Miscellaneous Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50300', 'name': 'Financial Expenses', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50301', 'name': 'Interest Expense', 'type': 'Expense', 'parent': '50300', 'nb': 'debit'},
    {'code': '50302', 'name': 'Bank Charges', 'type': 'Expense', 'parent': '50300', 'nb': 'debit'},
]


def seed_construction_coa():
    """Create the construction COA (two-pass). Idempotent; returns count created."""
    if Account.query.count() > 0:
        return 0
    by_code = {}
    for a in CONSTRUCTION_COA:
        acct = Account(code=a['code'], name=a['name'], account_type=a['type'],
                       normal_balance=a['nb'], is_active=True)
        db.session.add(acct)
        by_code[a['code']] = acct
    db.session.flush()  # assign ids
    for a in CONSTRUCTION_COA:
        if a['parent']:
            by_code[a['code']].parent_id = by_code[a['parent']].id
    db.session.commit()
    return len(CONSTRUCTION_COA)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_construction_coa_creates_magic_codes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): construction chart of accounts"
```

---

### Task 2: Reference data (settings, branch, admin, tax tables, 2025 periods)

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `seed_construction_coa()`.
- Produces: `seed_demo_baseline() -> dict` returning `{'branch': Branch, 'admin': User}`. Creates admin (`admin`/`admin123`), Main Branch (assigned to admin), company settings (Zhiyuan), VAT categories, Sales VAT categories, WHT codes (incl. `WC120`), and open `AccountingPeriod` rows for 2025-01..2025-06. Idempotent.

- [ ] **Step 1: Write the failing test**

```python
def test_seed_demo_baseline(db_session):
    from app.seeds.demo_seed import seed_demo_baseline
    from app.settings import AppSettings
    from app.withholding_tax.models import WithholdingTax
    from app.sales_vat_categories.models import SalesVATCategory
    from app.periods.models import AccountingPeriod

    refs = seed_demo_baseline()
    assert refs['admin'].username == 'admin'
    assert refs['branch'].code == 'MAIN'
    assert AppSettings.query.filter_by(key='company_name').first().value == \
        'Zhiyuan Construction Corporation'
    # WC120 (contractors 2%) present, with a sales_name (company is a contractor)
    wc120 = WithholdingTax.query.filter_by(code='WC120').first()
    assert wc120 is not None and float(wc120.rate) == 2.0
    assert wc120.sales_name
    assert SalesVATCategory.query.filter_by(code='V12').first() is not None
    # 2025 Jan-Jun periods open
    for m in range(1, 7):
        p = AccountingPeriod.query.filter_by(year=2025, month=m).first()
        assert p is not None and p.status == 'open'
    # Idempotent
    seed_demo_baseline()
    assert WithholdingTax.query.filter_by(code='WC120').count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_demo_baseline -v`
Expected: FAIL — `ImportError: cannot import name 'seed_demo_baseline'`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
COMPANY_SETTINGS = [
    {'key': 'company_name', 'value': 'Zhiyuan Construction Corporation'},
    {'key': 'trade_name', 'value': 'Zhiyuan Construction'},
    {'key': 'company_tin', 'value': '456-789-123-000'},
    {'key': 'company_address', 'value': '12 Mindanao Avenue, Project 8, Quezon City, Metro Manila'},
    {'key': 'postal_code', 'value': '1106'},
    {'key': 'rdo_code', 'value': '039'},
    {'key': 'tin_branch_code', 'value': '000'},
    {'key': 'fiscal_year_start', 'value': '01'},
    {'key': 'email', 'value': 'info@zhiyuanconstruction.ph'},
    {'key': 'phone', 'value': '(02) 8123-4567'},
    {'key': 'vat_registration_type', 'value': 'VAT'},
    {'key': 'officer_president', 'value': 'Wei Zhang'},
    {'key': 'officer_treasurer', 'value': 'Liang Chen'},
    {'key': 'officer_secretary', 'value': 'Mei Lin'},
    {'key': 'apv_print_access', 'value': 'draft_and_posted'},
    {'key': 'sv_print_access', 'value': 'draft_and_posted'},
    {'key': 'cd_print_access', 'value': 'draft_and_posted'},
    {'key': 'cr_print_access', 'value': 'draft_and_posted'},
    {'key': 'company_logo', 'value': ''},
    {'key': 'environment', 'value': 'demo'},
]

# code, name, rate, sales_name (None = purchase-only)
WHT_CODES = [
    {'code': 'WC120', 'name': 'Contractors/Subcontractors', 'rate': 2.00,
     'sales_name': 'Construction/Contractor (2% CWT)'},
    {'code': 'WC158', 'name': 'Income payments - Goods', 'rate': 1.00,
     'sales_name': 'Sale of Goods (1% CWT)'},
    {'code': 'WC160', 'name': 'Income payments - Services', 'rate': 2.00,
     'sales_name': 'Sale of Services (2% CWT)'},
    {'code': 'WC100', 'name': 'Rentals', 'rate': 5.00, 'sales_name': None},
    {'code': 'WC010', 'name': 'Professional Fees', 'rate': 10.00, 'sales_name': None},
]


def seed_demo_baseline():
    """COA + admin + branch + settings + tax tables + 2025 periods. Idempotent."""
    from app.users.models import User
    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod

    seed_construction_coa()

    # Admin
    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(username='admin', email='admin@zhiyuanconstruction.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Branch + assignment
    branch = Branch.query.filter_by(code='MAIN').first()
    if branch is None:
        branch = Branch(code='MAIN', name='Main Branch', address='Head Office', is_active=True)
        db.session.add(branch)
        db.session.commit()
    if branch not in admin.branches.all():
        admin.branches.append(branch)
        db.session.commit()

    # Settings
    if AppSettings.query.count() == 0:
        for s in COMPANY_SETTINGS:
            db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
        db.session.commit()

    # VAT (input) categories wired to Input VAT accounts
    if VATCategory.query.count() == 0:
        vat_acct = {a.code: a.id for a in Account.query.filter(
            Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
        for c in [
            {'code': 'VEX', 'name': 'VAT Exempt', 'rate': 0.00, 'acct': None},
            {'code': 'V0', 'name': 'VAT Zero-Rated', 'rate': 0.00, 'acct': None},
            {'code': 'INV', 'name': 'Invalid', 'rate': 0.00, 'acct': None},
            {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'acct': '10501'},
            {'code': 'V12DG', 'name': 'Input Tax Domestic Goods', 'rate': 12.00, 'acct': '10502'},
            {'code': 'V12SV', 'name': 'Input Tax Services', 'rate': 12.00, 'acct': '10503'},
            {'code': 'V12IM', 'name': 'Input Tax Importation', 'rate': 12.00, 'acct': '10504'},
        ]:
            db.session.add(VATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                       description='', is_active=True,
                                       input_vat_account_id=vat_acct.get(c['acct']) if c['acct'] else None))
        db.session.commit()

    # Sales (output) VAT categories wired to Output VAT Payable (20401)
    if SalesVATCategory.query.count() == 0:
        out_id = Account.query.filter_by(code='20401').first().id
        for c in [
            {'code': 'V12', 'name': 'VATable Sales (12%)', 'rate': 12.00, 'nature': 'regular', 'acct': out_id},
            {'code': 'V0', 'name': 'VAT Zero-Rated Sales', 'rate': 0.00, 'nature': 'zero_export', 'acct': None},
            {'code': 'VEX', 'name': 'VAT-Exempt Sales', 'rate': 0.00, 'nature': 'exempt', 'acct': None},
        ]:
            db.session.add(SalesVATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                            transaction_nature=c['nature'],
                                            output_vat_account_id=c['acct'], is_active=True))
        db.session.commit()

    # WHT codes
    if WithholdingTax.query.count() == 0:
        for w in WHT_CODES:
            db.session.add(WithholdingTax(code=w['code'], name=w['name'], description='',
                                          rate=w['rate'], sales_name=w['sales_name'], is_active=True))
        db.session.commit()

    # Open 2025 Jan-Jun periods
    for m in range(1, 7):
        AccountingPeriod.get_or_create_period(2025, m)

    return {'admin': admin, 'branch': branch}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_demo_baseline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): baseline reference data (settings, tax tables, 2025 periods)"
```

---

### Task 3: Master data (customers + vendors)

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `seed_demo_baseline()` (WHT codes must exist).
- Produces: `CUSTOMERS`, `VENDORS` (lists of dicts), `seed_demo_customers(admin_id) -> list[Customer]`, `seed_demo_vendors() -> list[Vendor]` (both idempotent, keyed on `code`). Customer codes `C001..`, vendor codes `V001..`.

- [ ] **Step 1: Write the failing test**

```python
def test_seed_master_data(db_session):
    from app.seeds.demo_seed import seed_demo_baseline, seed_demo_customers, seed_demo_vendors
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    refs = seed_demo_baseline()
    custs = seed_demo_customers(refs['admin'].id)
    vends = seed_demo_vendors()
    assert len(custs) == 7 and len(vends) == 10
    # WHT association resolved to real objects
    v_sub = Vendor.query.filter_by(name='Premier Electrical Subcontractor').first()
    assert [w.code for w in v_sub.withholding_taxes] == ['WC120']
    c1 = Customer.query.filter_by(code='C001').first()
    assert c1.default_vat_category == 'V12'
    assert [w.code for w in c1.withholding_taxes] == ['WC120']
    # Idempotent
    assert len(seed_demo_customers(refs['admin'].id)) == 7
    assert Customer.query.count() == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_master_data -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
# code, name, vat ('V12' VATable / 'VEX' non-VAT), wht (sales-side code or None)
CUSTOMERS = [
    {'code': 'C001', 'name': 'Vista Land Estates Inc.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C002', 'name': 'Megabuild Properties Corp.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C003', 'name': "St. Luke's Realty Development Corp.", 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C004', 'name': 'Ayala Township Development Inc.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C005', 'name': 'Robinsons Land Corporation', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C006', 'name': 'Greenfield District Devt Corp.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C007', 'name': 'Juan dela Cruz', 'vat': 'VEX', 'wht': None},
]

# code, name, vat (purchase category), wht, expense_code (default GL line account)
VENDORS = [
    {'code': 'V001', 'name': 'Holcim Philippines Inc.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V002', 'name': 'SteelAsia Manufacturing Corp.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V003', 'name': 'Wilcon Depot Inc.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V004', 'name': 'Premier Electrical Subcontractor', 'vat': 'V12SV', 'wht': 'WC120', 'expense_code': '50103'},
    {'code': 'V005', 'name': 'Reliable Plumbing & Sanitary Subcon', 'vat': 'V12SV', 'wht': 'WC120', 'expense_code': '50103'},
    {'code': 'V006', 'name': 'Manila Equipment Rentals Inc.', 'vat': 'V12SV', 'wht': 'WC100', 'expense_code': '50104'},
    {'code': 'V007', 'name': 'Meralco', 'vat': 'V12SV', 'wht': None, 'expense_code': '50221'},
    {'code': 'V008', 'name': 'Petron Corporation', 'vat': 'V12DG', 'wht': None, 'expense_code': '50280'},
    {'code': 'V009', 'name': 'Cruz & Associates Law Office', 'vat': 'V12SV', 'wht': 'WC010', 'expense_code': '50240'},
    {'code': 'V010', 'name': 'Pioneer Insurance & Surety Corp.', 'vat': 'V12SV', 'wht': 'WC160', 'expense_code': '50298'},
]


def _wht(code):
    from app.withholding_tax.models import WithholdingTax
    return WithholdingTax.query.filter_by(code=code).first() if code else None


def seed_demo_customers(admin_id):
    from app.customers.models import Customer
    out = []
    for i, spec in enumerate(CUSTOMERS):
        c = Customer.query.filter_by(code=spec['code']).first()
        if c is None:
            c = Customer(code=spec['code'], name=spec['name'],
                         tin=f"{200 + i}-100-200-000",
                         address='Metro Manila', payment_terms='Net 60',
                         default_vat_category=spec['vat'], default_wt_code=spec['wht'],
                         is_active=True, created_by_id=admin_id)
            db.session.add(c)
        wt = _wht(spec['wht'])
        c.withholding_taxes = [wt] if wt else []
        out.append(c)
    db.session.commit()
    return out


def seed_demo_vendors():
    from app.vendors.models import Vendor
    out = []
    for i, spec in enumerate(VENDORS):
        v = Vendor.query.filter_by(code=spec['code']).first()
        if v is None:
            v = Vendor(code=spec['code'], name=spec['name'],
                       tin=f"{300 + i}-400-500-000",
                       payment_terms='Net 30', default_vat_category=spec['vat'],
                       is_active=True)
            db.session.add(v)
        wt = _wht(spec['wht'])
        v.withholding_taxes = [wt] if wt else []
        out.append(v)
    db.session.commit()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_seed_master_data -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): construction master data (customers + vendors)"
```

---

### Task 4: Baseline build + UI validation checkpoint (operational — human gate)

**Files:** none changed. This task builds `instance/cas_demo.db` and pauses for owner UI validation.

**Interfaces:** Consumes Tasks 1–3 via a temporary inline call. Produces a validated baseline DB and owner sign-off on document shape before the generators are written.

- [ ] **Step 1: Point `.env` at the demo DB (back up the current value first)**

The dev box currently runs `sqlite:///ric.db`. Record it, then switch:

```bash
grep SQLALCHEMY_DATABASE_URI C:/envs/cas/.env   # confirm current = sqlite:///ric.db
```

Edit `.env`: set `SQLALCHEMY_DATABASE_URI=sqlite:///cas_demo.db`. **Do not delete `ric.db`.**

- [ ] **Step 2: Create the demo DB schema**

Run: `cd C:\envs\cas; flask db upgrade`
Expected: a fresh `instance/cas_demo.db` with all tables (Alembic prints "Context impl SQLiteImpl…", no per-step output on a fresh DB — normal).

- [ ] **Step 3: Seed the baseline only**

Run:
```bash
cd C:\envs\cas; flask shell -c "from app.seeds.demo_seed import seed_demo_baseline, seed_demo_customers, seed_demo_vendors; r=seed_demo_baseline(); seed_demo_customers(r['admin'].id); seed_demo_vendors(); print('baseline ok')"
```
Expected: `baseline ok`.

- [ ] **Step 4: Run the server and hand off for UI validation**

Start the dev server (`python flask_app.py`), log in `admin`/`admin123`. **Owner enters 2–5 sample documents per type (SI, CRV, APV, CDV, JV)** through the UI and confirms amounts/VAT/WHT/posting look correct. Capture any shape corrections.

- [ ] **Step 5: Record findings (no commit)**

Note any field/amount/account adjustments surfaced during UI entry; they feed Tasks 6–10. **STOP — get owner sign-off before continuing.** (The UI-entered samples may remain in `cas_demo.db`; the generators are idempotent by number, and Task 12 does the authoritative from-clean seed.)

---

### Task 5: Posting infrastructure (refs, money, doc numbers)

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Produces: `resolve_refs() -> dict` (resolves GL accounts the generators post against; raises `RuntimeError` if a magic code is missing). `next_doc_number(prefix, doc_date, counters) -> str` (`PREFIX-YYYY-MM-NNNN`, keyed on doc date). Module-level `_si_counter`/`_crv_counter` handled via a passed `counters` dict using keys `('SI',)`/`('CRV',)` for plain 5-digit continuous numbers.

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_refs_and_numbers(db_session):
    from app.seeds.demo_seed import seed_demo_baseline, resolve_refs, next_doc_number, si_number
    seed_demo_baseline()
    refs = resolve_refs()
    assert refs['ar'].code == '10201'
    assert refs['ap'].code == '20101'
    assert refs['cash_bank'].code == '10111'
    assert refs['revenue_contract'].code == '40101'
    counters = {}
    from datetime import date
    assert next_doc_number('AP', date(2025, 3, 4), counters) == 'AP-2025-03-0001'
    assert next_doc_number('AP', date(2025, 3, 4), counters) == 'AP-2025-03-0002'
    assert si_number(counters) == '00001'
    assert si_number(counters) == '00002'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_resolve_refs_and_numbers -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def resolve_refs():
    """Resolve the GL accounts the generators post against. Raises if missing."""
    def need(code):
        a = Account.query.filter_by(code=code).first()
        if a is None:
            raise RuntimeError(f"Required account {code} missing — run seed_demo_baseline first.")
        return a
    return {
        'ar': need('10201'),
        'cwt': need('10212'),
        'ap': need('20101'),
        'wt_payable': need('20301'),
        'output_vat': need('20401'),
        'cash_on_hand': need('10101'),
        'cash_bank': need('10111'),
        'revenue_contract': need('40101'),
        'revenue_rental': need('40201'),
        'cip': need('10310'),
        'equipment': need('11110'),
        'accum_dep_equipment': need('11111'),
        'dep_expense': need('50260'),
        'capital_stock': need('30101'),
        'apic': need('30102'),
        'expense': {code: need(code) for code in
                    ['50101', '50103', '50104', '50221', '50280', '50240', '50298', '50230']},
    }


def next_doc_number(prefix, doc_date, counters):
    """PREFIX-YYYY-MM-NNNN, sequencing per (prefix, year, month) on the DOC date."""
    key = (prefix, doc_date.year, doc_date.month)
    counters[key] = counters.get(key, 0) + 1
    return f'{prefix}-{doc_date.year}-{doc_date.month:02d}-{counters[key]:04d}'


def si_number(counters):
    counters[('SI',)] = counters.get(('SI',), 0) + 1
    return f"{counters[('SI',)]:05d}"


def crv_number(counters):
    counters[('CRV',)] = counters.get(('CRV',), 0) + 1
    return f"{counters[('CRV',)]:05d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_resolve_refs_and_numbers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): refs resolver + date-keyed doc numbering"
```

---

### Task 6: Sales Invoice generator

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `si_number()`.
- Produces: `build_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters) -> SalesInvoice` (posted, V12 12% output VAT, WC120 2% WHT for VATable customers; revenue → 40101). Sets `journal_entry_id`, commits.

- [ ] **Step 1: Write the failing test**

```python
def test_build_si_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_customers,
                                     resolve_refs, build_si)
    refs0 = seed_demo_baseline()
    custs = seed_demo_customers(refs0['admin'].id)
    refs = resolve_refs()
    counters = {}
    si = build_si(date(2025, 2, 10), custs[0], Decimal('560000.00'),
                  refs, refs0['admin'].id, refs0['branch'].id, counters)
    assert si.status == 'posted'
    assert si.journal_entry_id is not None
    je = si.journal_entry
    assert je.status == 'posted'
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    # VATable customer -> WHT applied
    assert si.withholding_tax_amount > 0
    assert si.invoice_number == '00001'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_build_si_posts_balanced -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def build_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    """Create one posted Sales Invoice (single line) + balanced posted JE."""
    from datetime import date as _date
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_invoices.views import _post_invoice_je
    from app.utils import ph_now

    vatable = customer_obj.default_vat_category == 'V12'
    wt = _wht('WC120') if vatable else None

    si = SalesInvoice(
        branch_id=branch_id,
        invoice_number=si_number(counters),
        invoice_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 60),
        customer_id=customer_obj.id,
        customer_name=customer_obj.name,
        customer_tin=customer_obj.tin,
        customer_address=customer_obj.address,
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    item = SalesInvoiceItem(
        line_number=1,
        description='Progress billing — construction works',
        amount=_money(gross_amount),
        vat_category='V12' if vatable else 'VEX',
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['revenue_contract'].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()   # extract VAT + WHT-on-net-of-rounded-VAT
    si.line_items.append(item)
    si.calculate_totals()
    db.session.add(si)
    db.session.flush()
    je = _post_invoice_je(si, admin_id)
    si.journal_entry_id = je.id
    db.session.commit()
    return si
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_build_si_posts_balanced -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): sales invoice generator"
```

---

### Task 7: Accounts Payable generator

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `next_doc_number()`, vendor specs.
- Produces: `build_apv(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters) -> AccountsPayable` (posted; expense → `vendor_spec['expense_code']`; VAT from `vendor_spec['vat']`; WHT from vendor's list; sets `vendor_invoice_number`/`date`).

- [ ] **Step 1: Write the failing test**

```python
def test_build_apv_posts_balanced(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_vendors,
                                     resolve_refs, build_apv, VENDORS)
    refs0 = seed_demo_baseline()
    vends = seed_demo_vendors()
    refs = resolve_refs()
    counters = {}
    ap = build_apv(date(2025, 3, 5), vends[0], VENDORS[0], Decimal('224000.00'),
                   refs, refs0['admin'].id, refs0['branch'].id, counters)
    assert ap.status == 'posted'
    je = ap.journal_entry
    assert je.status == 'posted'
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    assert ap.ap_number == 'AP-2025-03-0001'
    assert ap.vendor_invoice_number  # required when VAT/WHT > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_build_apv_posts_balanced -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def build_apv(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters):
    """Create one posted Accounts Payable (single line) + balanced posted JE."""
    from datetime import date as _date
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    from app.utils import ph_now

    vatable = vendor_spec['vat'].startswith('V12')
    wt = _wht(vendor_spec['wht'])
    apnum = next_doc_number('AP', doc_date, counters)

    ap = AccountsPayable(
        branch_id=branch_id,
        ap_number=apnum,
        ap_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        vendor_invoice_number=f'SI-{doc_date.year}{doc_date.month:02d}-{apnum[-4:]}',
        vendor_invoice_date=doc_date,
        payment_terms='Net 30',
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    item = AccountsPayableItem(
        line_number=1,
        description=f'{vendor_obj.name} — {doc_date.strftime("%b %Y")}',
        amount=_money(gross_amount),
        vat_category=vendor_spec['vat'],
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()
    ap.line_items.append(item)
    ap.calculate_totals()
    db.session.add(ap)
    db.session.flush()
    je = _post_ap_je(ap, admin_id)
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_build_apv_posts_balanced -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): accounts payable generator"
```

---

### Task 8: Cash Receipt generator (collect SIs + direct revenue)

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `crv_number()`, a posted `SalesInvoice`.
- Produces: `build_crv_collecting(doc_date, invoice, refs, admin_id, branch_id, counters, method='check') -> CashReceiptVoucher` (applies the invoice's full balance via an AR line; reduces SI balance). `build_crv_revenue(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters) -> CashReceiptVoucher` (direct rental income, V12, no WHT).

- [ ] **Step 1: Write the failing test**

```python
def test_build_crv_collects_invoice(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_customers,
                                     resolve_refs, build_si, build_crv_collecting)
    refs0 = seed_demo_baseline()
    custs = seed_demo_customers(refs0['admin'].id)
    refs = resolve_refs()
    counters = {}
    si = build_si(date(2025, 2, 10), custs[0], Decimal('560000.00'),
                  refs, refs0['admin'].id, refs0['branch'].id, counters)
    bal_before = Decimal(str(si.balance))
    assert bal_before > 0
    crv = build_crv_collecting(date(2025, 3, 12), si, refs,
                               refs0['admin'].id, refs0['branch'].id, counters)
    assert crv.status == 'posted'
    je = crv.journal_entry
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    # SI balance reduced / marked paid
    assert Decimal(str(si.balance)) < bal_before
    assert si.status in ('paid', 'partially_paid')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_build_crv_collects_invoice -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def _new_crv(doc_date, customer_obj, refs, admin_id, branch_id, counters, method):
    from app.cash_receipts.models import CashReceiptVoucher
    from app.utils import ph_now
    cash = refs['cash_bank'] if method == 'check' else refs['cash_on_hand']
    crv = CashReceiptVoucher(
        branch_id=branch_id,
        crv_number=crv_number(counters),
        crv_date=doc_date,
        customer_id=customer_obj.id,
        customer_name=customer_obj.name,
        customer_tin=customer_obj.tin,
        payment_method=method,
        cash_account_id=cash.id,
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        crv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters.get(("CRV",), 0):04d}'
        crv.check_date = doc_date
        crv.check_bank = 'BDO'
    return crv


def build_crv_collecting(doc_date, invoice, refs, admin_id, branch_id, counters, method='check'):
    from app.cash_receipts.models import CRVArLine
    from app.cash_receipts.views import _post_crv_je, _apply_ar_collections
    crv = _new_crv(doc_date, invoice.customer, refs, admin_id, branch_id, counters, method)
    crv.ar_lines.append(CRVArLine(
        line_number=1,
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        original_balance=invoice.balance,
        amount_applied=_money(invoice.balance),
    ))
    crv.calculate_totals()
    db.session.add(crv)
    db.session.flush()
    je = _post_crv_je(crv, admin_id)
    crv.journal_entry_id = je.id
    _apply_ar_collections(crv)
    db.session.commit()
    return crv


def build_crv_revenue(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    from app.cash_receipts.models import CRVRevenueLine
    from app.cash_receipts.views import _post_crv_je
    crv = _new_crv(doc_date, customer_obj, refs, admin_id, branch_id, counters, 'cash')
    line = CRVRevenueLine(
        line_number=1,
        description='Equipment rental income',
        amount=_money(gross_amount),
        vat_category='V12',
        vat_rate=Decimal('12.00'),
        account_id=refs['revenue_rental'].id,
        wt_rate=Decimal('0.00'),
    )
    line.calculate_amounts()
    crv.revenue_lines.append(line)
    crv.calculate_totals()
    db.session.add(crv)
    db.session.flush()
    je = _post_crv_je(crv, admin_id)
    crv.journal_entry_id = je.id
    db.session.commit()
    return crv
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_build_crv_collects_invoice -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): cash receipt generators (collect + direct revenue)"
```

---

### Task 9: Cash Disbursement generator (pay APs + direct expense)

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `next_doc_number()`, a posted `AccountsPayable`.
- Produces: `build_cdv_paying(doc_date, ap, refs, admin_id, branch_id, counters, method='check') -> CashDisbursementVoucher` (pays the AP's full balance; reduces AP balance). `build_cdv_expense(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters) -> CashDisbursementVoucher` (direct expense).

- [ ] **Step 1: Write the failing test**

```python
def test_build_cdv_pays_ap(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, seed_demo_vendors,
                                     resolve_refs, build_apv, build_cdv_paying, VENDORS)
    refs0 = seed_demo_baseline()
    vends = seed_demo_vendors()
    refs = resolve_refs()
    counters = {}
    ap = build_apv(date(2025, 3, 5), vends[0], VENDORS[0], Decimal('224000.00'),
                   refs, refs0['admin'].id, refs0['branch'].id, counters)
    bal_before = Decimal(str(ap.balance))
    cdv = build_cdv_paying(date(2025, 4, 5), ap, refs,
                           refs0['admin'].id, refs0['branch'].id, counters)
    assert cdv.status == 'posted'
    je = cdv.journal_entry
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert d == c
    assert Decimal(str(ap.balance)) < bal_before
    assert ap.status in ('paid', 'partially_paid')
    assert cdv.cdv_number == 'CD-2025-04-0001'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_build_cdv_pays_ap -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def _new_cdv(doc_date, vendor_obj, refs, admin_id, branch_id, counters, method):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.utils import ph_now
    cash = refs['cash_bank'] if method == 'check' else refs['cash_on_hand']
    cdv = CashDisbursementVoucher(
        branch_id=branch_id,
        cdv_number=next_doc_number('CD', doc_date, counters),
        cdv_date=doc_date,
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        payment_method=method,
        cash_account_id=cash.id,
        notes='',
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        cdv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters[("CD", doc_date.year, doc_date.month)]:04d}'
        cdv.check_date = doc_date
        cdv.check_bank = 'BDO'
    return cdv


def build_cdv_paying(doc_date, ap, refs, admin_id, branch_id, counters, method='check'):
    from app.cash_disbursements.models import CDVApLine
    from app.cash_disbursements.views import _post_cdv_je, _apply_ap_payments
    cdv = _new_cdv(doc_date, ap.vendor, refs, admin_id, branch_id, counters, method)
    cdv.ap_lines.append(CDVApLine(
        line_number=1,
        ap_id=ap.id,
        ap_number=ap.ap_number,
        original_balance=ap.balance,
        amount_applied=_money(ap.balance),
    ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, admin_id)
    cdv.journal_entry_id = je.id
    _apply_ap_payments(cdv)
    db.session.commit()
    return cdv


def build_cdv_expense(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters, method='cash'):
    from app.cash_disbursements.models import CDVExpenseLine
    from app.cash_disbursements.views import _post_cdv_je
    vatable = vendor_spec['vat'].startswith('V12')
    wt = _wht(vendor_spec['wht'])
    cdv = _new_cdv(doc_date, vendor_obj, refs, admin_id, branch_id, counters, method)
    line = CDVExpenseLine(
        line_number=1,
        description=f'{vendor_obj.name} — {doc_date.strftime("%b %Y")}',
        amount=_money(gross_amount),
        vat_category=vendor_spec['vat'],
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    line.calculate_amounts()
    cdv.expense_lines.append(line)
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, admin_id)
    cdv.journal_entry_id = je.id
    db.session.commit()
    return cdv
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_build_cdv_pays_ap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): cash disbursement generators (pay AP + direct expense)"
```

---

### Task 10: Journal Voucher + stockholder investments

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`.
- Produces: `build_jv(doc_date, lines, refs, admin_id, branch_id, *, entry_type='adjustment', description, reference='') -> JournalEntry` where `lines` is a list of `(account, debit, credit)` tuples (account = an `Account`). `seed_stockholder_investments(refs, admin_id, branch_id) -> list[JournalEntry]` (three opening contributions).

- [ ] **Step 1: Write the failing test**

```python
def test_jv_and_stockholder_investments(db_session):
    from datetime import date
    from decimal import Decimal
    from app.seeds.demo_seed import (seed_demo_baseline, resolve_refs, build_jv,
                                     seed_stockholder_investments)
    refs0 = seed_demo_baseline()
    refs = resolve_refs()
    jv = build_jv(date(2025, 1, 31),
                  [(refs['dep_expense'], Decimal('15000.00'), Decimal('0.00')),
                   (refs['accum_dep_equipment'], Decimal('0.00'), Decimal('15000.00'))],
                  refs, refs0['admin'].id, refs0['branch'].id,
                  entry_type='adjustment', description='Monthly depreciation Jan 2025')
    assert jv.status == 'posted' and jv.is_balanced is True
    assert jv.entry_number.startswith('JV-2025-01-')

    inv = seed_stockholder_investments(refs, refs0['admin'].id, refs0['branch'].id)
    assert len(inv) == 3
    for je in inv:
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
        assert d == c and je.status == 'posted'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_jv_and_stockholder_investments -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def build_jv(doc_date, lines, refs, admin_id, branch_id, *,
             entry_type='adjustment', description, reference=''):
    """Create one posted Journal Voucher. lines = [(Account, debit, credit), ...]."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.journal_entries.utils import generate_jv_number
    from app.utils import ph_now

    je = JournalEntry(
        entry_number=generate_jv_number(branch_id),
        entry_date=doc_date,
        description=description,
        reference=reference,
        entry_type=entry_type,
        branch_id=branch_id,
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    for i, (acct, dr, cr) in enumerate(lines, start=1):
        je.lines.append(JournalEntryLine(
            line_number=i, account_id=acct.id,
            debit_amount=_money(dr), credit_amount=_money(cr),
            description=description,
        ))
    db.session.add(je)
    db.session.flush()
    je.calculate_totals()   # sets total_debit/credit/is_balanced
    db.session.commit()
    return je


def seed_stockholder_investments(refs, admin_id, branch_id):
    """Three opening equity contributions (2 cash, 1 in-kind equipment)."""
    from datetime import date
    out = []
    # Wei Zhang — cash: 5,000,000 (4,000,000 par + 1,000,000 premium)
    out.append(build_jv(date(2025, 1, 2), [
        (refs['cash_bank'], Decimal('5000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('4000000.00')),
        (refs['apic'], Decimal('0.00'), Decimal('1000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Wei Zhang (cash)'))
    # Liang Chen — cash: 3,000,000 par
    out.append(build_jv(date(2025, 1, 2), [
        (refs['cash_bank'], Decimal('3000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('3000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Liang Chen (cash)'))
    # Mei Lin — in-kind: construction equipment 2,000,000 par
    out.append(build_jv(date(2025, 1, 3), [
        (refs['equipment'], Decimal('2000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('2000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Mei Lin (construction equipment, in-kind)'))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_jv_and_stockholder_investments -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/demo_seed.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): journal voucher + stockholder investments"
```

---

### Task 11: Orchestrator + `seed-demo` CLI + integrity test

**Files:**
- Modify: `app/seeds/demo_seed.py`
- Modify: `app/__init__.py` (after the `seed-history` registration, ~line 299)
- Test: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: every generator above.
- Produces: `generate_demo_transactions(refs, admin_id, branch_id, *, end=date(2025, 6, 19), rng_seed=20250101) -> dict` (summary counts). `run_seed_demo(reset=False) -> dict`. CLI `seed-demo`.

- [ ] **Step 1: Write the failing test**

```python
def test_run_seed_demo_full_balances(db_session):
    from decimal import Decimal
    from app.seeds.demo_seed import run_seed_demo
    from app.journal_entries.models import JournalEntry
    from app.sales_invoices.models import SalesInvoice
    from app.accounts_payable.models import AccountsPayable
    from app.cash_receipts.models import CashReceiptVoucher
    from app.cash_disbursements.models import CashDisbursementVoucher

    summary = run_seed_demo(reset=False)
    assert summary['si'] >= 8 and summary['ap'] >= 8
    assert summary['crv'] >= 6 and summary['cdv'] >= 6 and summary['jv'] >= 5
    # Every posted document type exists
    assert SalesInvoice.query.filter_by(status='posted').count() >= 8
    assert AccountsPayable.query.filter_by(status='posted').count() >= 8
    assert CashReceiptVoucher.query.count() >= 6
    assert CashDisbursementVoucher.query.count() >= 6
    # Trial balance: total posted debits == total posted credits
    tot_d = tot_c = Decimal('0')
    for je in JournalEntry.query.filter_by(status='posted').all():
        tot_d += sum((l.debit_amount for l in je.lines.all()), Decimal('0'))
        tot_c += sum((l.credit_amount for l in je.lines.all()), Decimal('0'))
    assert tot_d == tot_c
    assert summary['unbalanced'] == 0
    # All transactions within Jan 1 - Jun 19 2025
    from datetime import date
    for si in SalesInvoice.query.all():
        assert date(2025, 1, 1) <= si.invoice_date <= date(2025, 6, 19)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_demo_seed.py::test_run_seed_demo_full_balances -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/seeds/demo_seed.py`:

```python
def _clamp_day(year, month, day, end):
    last = calendar.monthrange(year, month)[1]
    return min(date(year, month, min(day, last)), end)


def _count_unbalanced_jes():
    from app.journal_entries.models import JournalEntry
    bad = 0
    for je in JournalEntry.query.filter_by(status='posted').all():
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        if d != c:
            bad += 1
    return bad


def generate_demo_transactions(refs, admin_id, branch_id, *, end=date(2025, 6, 19),
                               rng_seed=20250101):
    """Generate the Jan 1 - Jun 19 2025 document set. Deterministic."""
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    rng = random.Random(rng_seed)
    counters = {}
    summary = {'si': 0, 'ap': 0, 'crv': 0, 'cdv': 0, 'jv': 0, 'unbalanced': 0}

    custs = [c for c in (Customer.query.filter_by(code=s['code']).first() for s in CUSTOMERS) if c]
    vends = {v.code: v for v in Vendor.query.all()}
    vatable_custs = [c for c in custs if c.default_vat_category == 'V12']

    # Stockholder investments first (opening equity)
    seed_stockholder_investments(refs, admin_id, branch_id)
    summary['jv'] += 3

    posted_sis, posted_aps = [], []
    months = [(2025, m) for m in range(1, 7)]
    for (y, m) in months:
        # ~2 SIs / month (skip days past end via clamp)
        for _ in range(2):
            cust = rng.choice(vatable_custs)
            d = _clamp_day(y, m, rng.randint(5, 20), end)
            if d > end:
                continue
            gross = _money(rng.uniform(300000, 900000))
            si = build_si(d, cust, gross, refs, admin_id, branch_id, counters)
            posted_sis.append(si)
            summary['si'] += 1
        # ~2 APs / month
        for _ in range(2):
            spec = rng.choice(VENDORS)
            vobj = vends[spec['code']]
            d = _clamp_day(y, m, rng.randint(3, 18), end)
            if d > end:
                continue
            gross = _money(rng.uniform(80000, 350000))
            ap = build_apv(d, vobj, spec, gross, refs, admin_id, branch_id, counters)
            posted_aps.append(ap)
            summary['ap'] += 1
        # depreciation JV each month
        d = _clamp_day(y, m, 28, end)
        build_jv(d, [(refs['dep_expense'], Decimal('25000.00'), Decimal('0.00')),
                     (refs['accum_dep_equipment'], Decimal('0.00'), Decimal('25000.00'))],
                 refs, admin_id, branch_id, entry_type='adjustment',
                 description=f'Monthly depreciation {d.strftime("%b %Y")}')
        summary['jv'] += 1

    # Collect ~70% of SIs, pay ~70% of APs (payment dated 20-40 days later, clamped)
    for si in posted_sis:
        if rng.random() < 0.70:
            pay = _clamp_day(si.invoice_date.year, si.invoice_date.month,
                             si.invoice_date.day, end)
            pay = min(date.fromordinal(si.invoice_date.toordinal() + rng.randint(20, 40)), end)
            if pay >= si.invoice_date:
                build_crv_collecting(pay, si, refs, admin_id, branch_id, counters,
                                     method='check' if rng.random() < 0.6 else 'cash')
                summary['crv'] += 1
    for ap in posted_aps:
        if rng.random() < 0.70:
            pay = min(date.fromordinal(ap.ap_date.toordinal() + rng.randint(15, 35)), end)
            if pay >= ap.ap_date:
                spec = next(s for s in VENDORS if s['code'] == ap.vendor.code)
                build_cdv_paying(pay, ap, refs, admin_id, branch_id, counters,
                                 method='check' if rng.random() < 0.6 else 'cash')
                summary['cdv'] += 1

    # A couple direct-revenue CRVs and direct-expense CDVs for variety
    build_crv_revenue(date(2025, 4, 15), vatable_custs[0], _money('56000.00'),
                      refs, admin_id, branch_id, counters)
    summary['crv'] += 1
    for spec_code, day, mon in [('V007', 10, 2), ('V008', 12, 5)]:
        spec = next(s for s in VENDORS if s['code'] == spec_code)
        build_cdv_expense(_clamp_day(2025, mon, day, end), vends[spec_code], spec,
                          _money(rng.uniform(8000, 40000)), refs, admin_id, branch_id, counters)
        summary['cdv'] += 1

    # A reclassification JV + a reversal-style JV for variety
    build_jv(date(2025, 6, 18),
             [(refs['cip'], Decimal('120000.00'), Decimal('0.00')),
              (refs['expense']['50101'], Decimal('0.00'), Decimal('120000.00'))],
             refs, admin_id, branch_id, entry_type='reclassification',
             description='Reclassify materials to CIP')
    summary['jv'] += 1

    summary['unbalanced'] = _count_unbalanced_jes()
    return summary


def run_seed_demo(reset=False):
    """Optionally reset, build baseline + master data + transactions. Returns summary."""
    if reset:
        db.drop_all()
        db.create_all()
    refs0 = seed_demo_baseline()
    seed_demo_customers(refs0['admin'].id)
    seed_demo_vendors()
    refs = resolve_refs()
    return generate_demo_transactions(refs, refs0['admin'].id, refs0['branch'].id)
```

Then register the CLI in `app/__init__.py` immediately after the `seed-history` command block (after its final `print(...)`, before the `# Request/Response logging middleware` comment near line 301):

```python
    @app.cli.command('seed-demo')
    def seed_demo_command():
        """Build the Zhiyuan Construction demo dataset into the active DB."""
        from app.seeds.demo_seed import run_seed_demo
        summary = run_seed_demo(reset=False)
        print("\n[OK] Demo seed complete:")
        for k in ('si', 'ap', 'crv', 'cdv', 'jv', 'unbalanced'):
            print(f"  {k:>12}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_demo_seed.py::test_run_seed_demo_full_balances -v`
Expected: PASS.

- [ ] **Step 5: Run the whole demo-seed test file**

Run: `pytest tests/integration/test_demo_seed.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/seeds/demo_seed.py app/__init__.py tests/integration/test_demo_seed.py
git commit -m "feat(demo-seed): orchestrator, seed-demo CLI, trial-balance integrity test"
```

---

### Task 12: Build the demo DB + verify + seed_data.py cleanup (operational)

**Files:**
- Modify: `app/seeds/seed_data.py` (cleanup only).

**Interfaces:** Produces the deliverable `instance/cas_demo.db` and a small docs/seed cleanup.

- [ ] **Step 1: Rebuild `cas_demo.db` from clean via the CLI**

With `.env` still pointing at `sqlite:///cas_demo.db` (from Task 4), rebuild authoritatively:

```bash
cd C:\envs\cas
rm -f instance/cas_demo.db
flask db upgrade
flask seed-demo
```
Expected: the `[OK] Demo seed complete` summary with `unbalanced: 0`.

- [ ] **Step 2: Verify in a shell (trial balance + counts)**

```bash
cd C:\envs\cas; flask shell -c "from app.journal_entries.models import JournalEntry; from decimal import Decimal; jes=JournalEntry.query.filter_by(status='posted').all(); d=sum((l.debit_amount for je in jes for l in je.lines.all()), Decimal('0')); c=sum((l.credit_amount for je in jes for l in je.lines.all()), Decimal('0')); print('TB debit==credit:', d==c, d)"
```
Expected: `TB debit==credit: True ...`.

- [ ] **Step 3: Spot-check in the UI (manual)**

`python flask_app.py`, log in `admin`/`admin123`, confirm SI/CRV/APV/CDV/JV lists are populated, company name reads "Zhiyuan Construction Corporation", and a sample posted document's journal entry balances. Confirm with owner.

- [ ] **Step 4: Restore `.env` to the RIC instance**

Edit `.env`: set `SQLALCHEMY_DATABASE_URI=sqlite:///ric.db` (the dev box default). `cas_demo.db` remains on disk as the demo deliverable; `ric.db` was never touched.

- [ ] **Step 5: seed_data.py cleanup (small, no behavior change)**

In `app/__init__.py` the `seed-db` CLI prints `Password: ac112358321` (line ~280) while `seed_all()` actually sets `admin123`. Fix the printed line to match reality:

```python
        print("  3. Password: admin123")
```
(Only correct the mismatched print string; do not change the seeder logic.)

- [ ] **Step 6: Run the full demo-seed test suite once more + commit**

Run: `pytest tests/integration/test_demo_seed.py -v`
Expected: all PASS.

```bash
git add app/__init__.py
git commit -m "chore(seed): fix seed-db CLI printed password to match seeder (admin123)"
```

Note: `cas_demo.db` is gitignored (per `*.db`); it is the on-disk demo deliverable, not committed.

---

## Self-Review

**Spec coverage:**
- Construction COA (fixed skeleton + magic codes) → Task 1. ✓
- `seed_data.py` refresh/cleanup → Task 12 (Step 5). ✓
- Reference data incl. WC120, Sales VAT, open 2025 periods → Task 2. ✓
- Fabricated master data (7 customers, 10 vendors) → Task 3. ✓
- ~50–58 posted SI/CR/AP/CD/JV Jan 1–Jun 19 2025 → Tasks 6–11. ✓
- Stockholder investments → Task 10. ✓
- Reuse `_post_*_je` helpers → Tasks 6–9 (each calls the helper, sets `journal_entry_id`, commits). ✓
- UI validation (2–5 samples/type) before full seed → Task 4 checkpoint. ✓
- Target `cas_demo.db`, RIC untouched, `.env` switch + restore → Tasks 4 & 12. ✓
- Idempotency → seeders skip-by-code/number; `run_seed_demo(reset=False)` default. ✓
- Trial-balance integrity test → Task 11. ✓

**Placeholder scan:** none — every step has complete code/commands.

**Type consistency:** generator signatures consistent across tasks (`build_si`, `build_apv`, `build_crv_collecting`, `build_crv_revenue`, `build_cdv_paying`, `build_cdv_expense`, `build_jv`, `seed_stockholder_investments`, `resolve_refs`, `next_doc_number`, `si_number`, `crv_number`, `generate_demo_transactions`, `run_seed_demo`). `refs` dict keys (`ar`, `ap`, `cash_bank`, `revenue_contract`, `expense[...]`, `capital_stock`, `apic`, `equipment`, `accum_dep_equipment`, `dep_expense`, `cip`, `revenue_rental`) defined in Task 5 and consumed unchanged in Tasks 6–11.

**Implementer note:** before each generator's first green run, verify the exact line-collection attribute names against the models if a test errors (`si.line_items`, `ap.line_items`, `crv.ar_lines`/`crv.revenue_lines`, `cdv.ap_lines`/`cdv.expense_lines`, `je.lines`) — these match `app/seeds/history_seed.py` usage but the model is the source of truth.
