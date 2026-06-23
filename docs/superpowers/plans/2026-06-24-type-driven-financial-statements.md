# Type-Driven Financial Statements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the Income Statement, Balance Sheet, and Cash Flow from each account's `account_type` (+ `classification`) instead of code prefixes, add a richer FS type taxonomy, roll parents into single expandable lines, and let any FS line drill into its ledger.

**Architecture:** A new `app/accounts/account_types.py` module is the single source of truth for the 11-value type taxonomy, the Current/Non-Current classifications, and the legacy base-category mapping. `app/reports/sections.py` holds declarative IS/BS section tables and a shared parent-rollup helper. The three generators in `app/reports/financial.py` are rewritten to read those tables. A new JSON endpoint + shared modal partial provide ledger drill-down.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Jinja2, vanilla JS (no framework), openpyxl (Excel), pytest.

## Global Constraints

- Target DB is `cas_demo.db` only (current `.env`). Do not migrate `cas.db`/`ric.db`.
- No schema/migration: `Account.account_type` and `Account.classification` columns already exist (both `String(20)`). Only their allowed *values* change.
- `normal_balance` values are lowercase `'debit'`/`'credit'` (matches live `cas_demo.db` data and `seed_data.py`).
- Preserve hardcoded posting codes exactly: `10201` AR-Trade, `10212` Creditable WHT Receivable, `20101` AP-Trade, `20301` WHT Payable-Expanded, `30201` Retained Earnings, `30301` Income Summary.
- `generate_income_statement(...)['net_income']` key + semantics must be preserved (Balance Sheet + Year-End Close depend on it). Closing entries stay excluded: `JournalEntry.entry_type.notin_(['closing','closing_reversal'])`.
- No JS `confirm()`/`alert()`/`prompt()`; custom modal with `{{ csrf_token() }}` where a form is involved. No hardcoded styling — use existing design tokens / CSS variables.
- After editing any `app/static/*` asset, bump the `?v=N` cache-buster on every template that links it.
- Every CRUD write asserts an audit entry in tests (N/A for read-only report endpoints).
- Run targeted pytest for verification; do NOT run the full suite as a gate (user-invoked only).

---

### Task 1: Account type taxonomy module

**Files:**
- Create: `app/accounts/account_types.py`
- Modify: `app/accounts/models.py` (add `base_category` property)
- Test: `tests/unit/test_account_types.py`

**Interfaces:**
- Produces: `ACCOUNT_TYPES: list[str]`, `BS_TYPES: list[str]`, `IS_TYPES: list[str]`, `CLASSIFICATIONS: list[str]`, `TYPES_NEEDING_CLASSIFICATION: tuple[str,...]`, `BASE_CATEGORY: dict[str,str]`, `DEFAULT_NORMAL_BALANCE: dict[str,str]`, and `Account.base_category -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_account_types.py
import pytest
from app.accounts.account_types import (
    ACCOUNT_TYPES, BS_TYPES, IS_TYPES, CLASSIFICATIONS,
    TYPES_NEEDING_CLASSIFICATION, BASE_CATEGORY, DEFAULT_NORMAL_BALANCE)
from app.accounts.models import Account

pytestmark = [pytest.mark.unit]

def test_taxonomy_shape():
    assert BS_TYPES == ['Asset', 'Liability', 'Equity']
    assert IS_TYPES == ['Revenue', 'Contra-Revenue', 'Cost of Goods Sold',
                        'Selling Expense', 'Administrative Expense',
                        'Other Income', 'Other Expense', 'Income Tax Expense']
    assert ACCOUNT_TYPES == BS_TYPES + IS_TYPES
    assert CLASSIFICATIONS == ['Current', 'Non-Current']
    assert TYPES_NEEDING_CLASSIFICATION == ('Asset', 'Liability')

def test_every_type_maps_to_base_and_normal_balance():
    for t in ACCOUNT_TYPES:
        assert BASE_CATEGORY[t] in ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense')
        assert DEFAULT_NORMAL_BALANCE[t] in ('debit', 'credit')

def test_base_category_examples():
    assert BASE_CATEGORY['Contra-Revenue'] == 'Revenue'
    assert BASE_CATEGORY['Cost of Goods Sold'] == 'Expense'
    assert BASE_CATEGORY['Other Income'] == 'Revenue'
    assert BASE_CATEGORY['Income Tax Expense'] == 'Expense'

def test_account_base_category_property():
    assert Account(code='1', name='x', account_type='Cost of Goods Sold',
                   normal_balance='debit').base_category == 'Expense'
    assert Account(code='2', name='y', account_type='Other Income',
                   normal_balance='credit').base_category == 'Revenue'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_account_types.py -q -o addopts=""`
Expected: FAIL — `ModuleNotFoundError: app.accounts.account_types`.

- [ ] **Step 3: Write the module + property**

```python
# app/accounts/account_types.py
"""Canonical Chart-of-Accounts type taxonomy and FS classification.

`account_type` is the single source of truth for financial-statement placement.
`classification` ('Current'/'Non-Current') refines Asset/Liability for the Balance Sheet.
`BASE_CATEGORY` maps each rich type back to one of the five legacy base categories so
normal-balance defaults and any residual base-type logic keep working.
"""

BS_TYPES = ['Asset', 'Liability', 'Equity']
IS_TYPES = ['Revenue', 'Contra-Revenue', 'Cost of Goods Sold',
            'Selling Expense', 'Administrative Expense',
            'Other Income', 'Other Expense', 'Income Tax Expense']
ACCOUNT_TYPES = BS_TYPES + IS_TYPES

CLASSIFICATIONS = ['Current', 'Non-Current']
TYPES_NEEDING_CLASSIFICATION = ('Asset', 'Liability')

BASE_CATEGORY = {
    'Asset': 'Asset', 'Liability': 'Liability', 'Equity': 'Equity',
    'Revenue': 'Revenue', 'Contra-Revenue': 'Revenue',
    'Cost of Goods Sold': 'Expense', 'Selling Expense': 'Expense',
    'Administrative Expense': 'Expense', 'Other Income': 'Revenue',
    'Other Expense': 'Expense', 'Income Tax Expense': 'Expense',
}

DEFAULT_NORMAL_BALANCE = {
    'Asset': 'debit', 'Liability': 'credit', 'Equity': 'credit',
    'Revenue': 'credit', 'Contra-Revenue': 'debit',
    'Cost of Goods Sold': 'debit', 'Selling Expense': 'debit',
    'Administrative Expense': 'debit', 'Other Income': 'credit',
    'Other Expense': 'debit', 'Income Tax Expense': 'debit',
}
```

```python
# app/accounts/models.py — add inside class Account (after to_dict or near top)
    @property
    def base_category(self):
        """Map the rich account_type back to a legacy base category
        (Asset/Liability/Equity/Revenue/Expense)."""
        from app.accounts.account_types import BASE_CATEGORY
        return BASE_CATEGORY.get(self.account_type, self.account_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_account_types.py -q -o addopts=""`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/accounts/account_types.py app/accounts/models.py tests/unit/test_account_types.py
git commit -m "feat(accounts): canonical FS type taxonomy + base_category"
```

---

### Task 2: Shared section tables + parent-rollup helper

**Files:**
- Create: `app/reports/sections.py`
- Test: `tests/unit/test_report_sections.py`

**Interfaces:**
- Consumes: `app.accounts.account_types`.
- Produces:
  - `IS_SECTIONS: list[dict]` — each `{'key','label','types','sign','subtotal'}`.
  - `BS_SECTIONS: list[dict]` — each `{'key','label','type','credit_positive','divisions'}`.
  - `rollup(rows, accounts) -> list[dict]` where `rows` is a list of
    `{'account_id','code','name','amount'}` and `accounts` is the full active
    account list; returns top-level group lines:
    `[{'code','name','account_id','total','children':[{'code','name','account_id','amount'}]}]`.
    A leaf with no parent becomes a single-line group with empty `children`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_report_sections.py
import pytest
from app import db
from app.accounts.models import Account
from app.reports.sections import IS_SECTIONS, BS_SECTIONS, rollup

pytestmark = [pytest.mark.unit]

def test_is_sections_cover_all_is_types():
    from app.accounts.account_types import IS_TYPES
    covered = [t for s in IS_SECTIONS for t in s['types']]
    assert covered == IS_TYPES
    # subtotal chain present in order
    subs = [s['subtotal'] for s in IS_SECTIONS if s['subtotal']]
    assert subs == ['Net Sales', 'Gross Profit', 'Operating Income',
                    'Income Before Tax', 'Net Income']

def test_bs_sections():
    keys = [s['key'] for s in BS_SECTIONS]
    assert keys == ['assets', 'liabilities', 'equity']
    assets = next(s for s in BS_SECTIONS if s['key'] == 'assets')
    assert assets['divisions'] == ['Current', 'Non-Current']
    assert next(s for s in BS_SECTIONS if s['key'] == 'equity')['divisions'] is None

def test_rollup_groups_children_under_parent(db_session):
    p = Account(code='50220', name='G&A', account_type='Administrative Expense',
                normal_balance='debit', is_active=True)
    db.session.add(p); db.session.commit()
    c1 = Account(code='50221', name='Office Salaries', account_type='Administrative Expense',
                 normal_balance='debit', is_active=True, parent_id=p.id)
    c2 = Account(code='50224', name='Office Rent', account_type='Administrative Expense',
                 normal_balance='debit', is_active=True, parent_id=p.id)
    db.session.add_all([c1, c2]); db.session.commit()
    accounts = Account.query.all()
    rows = [{'account_id': c1.id, 'code': '50221', 'name': 'Office Salaries', 'amount': 100.0},
            {'account_id': c2.id, 'code': '50224', 'name': 'Office Rent', 'amount': 50.0}]
    lines = rollup(rows, accounts)
    assert len(lines) == 1
    assert lines[0]['code'] == '50220'
    assert lines[0]['total'] == 150.0
    assert {ch['code'] for ch in lines[0]['children']} == {'50221', '50224'}

def test_rollup_orphan_leaf_is_its_own_line(db_session):
    a = Account(code='50101', name='COGS', account_type='Cost of Goods Sold',
                normal_balance='debit', is_active=True)
    db.session.add(a); db.session.commit()
    rows = [{'account_id': a.id, 'code': '50101', 'name': 'COGS', 'amount': 400.0}]
    lines = rollup(rows, Account.query.all())
    assert lines == [{'code': '50101', 'name': 'COGS', 'account_id': a.id,
                      'total': 400.0, 'children': []}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_report_sections.py -q -o addopts=""`
Expected: FAIL — `ModuleNotFoundError: app.reports.sections`.

- [ ] **Step 3: Write the module**

```python
# app/reports/sections.py
"""Declarative FS section tables + parent roll-up, shared by the generators."""

IS_SECTIONS = [
    {'key': 'revenue',        'label': 'Sales',                           'types': ['Revenue'],                'sign': 1,  'subtotal': None},
    {'key': 'contra_revenue', 'label': 'Less: Sales Returns & Discounts', 'types': ['Contra-Revenue'],         'sign': -1, 'subtotal': 'Net Sales'},
    {'key': 'cogs',           'label': 'Cost of Goods Sold',              'types': ['Cost of Goods Sold'],     'sign': -1, 'subtotal': 'Gross Profit'},
    {'key': 'selling',        'label': 'Selling Expenses',                'types': ['Selling Expense'],        'sign': -1, 'subtotal': None},
    {'key': 'admin',          'label': 'Administrative Expenses',         'types': ['Administrative Expense'], 'sign': -1, 'subtotal': 'Operating Income'},
    {'key': 'other_income',   'label': 'Other Income',                    'types': ['Other Income'],           'sign': 1,  'subtotal': None},
    {'key': 'other_expense',  'label': 'Other Expenses',                  'types': ['Other Expense'],          'sign': -1, 'subtotal': 'Income Before Tax'},
    {'key': 'income_tax',     'label': 'Income Tax Expense',              'types': ['Income Tax Expense'],     'sign': -1, 'subtotal': 'Net Income'},
]

BS_SECTIONS = [
    {'key': 'assets',      'label': 'ASSETS',      'type': 'Asset',     'credit_positive': False, 'divisions': ['Current', 'Non-Current']},
    {'key': 'liabilities', 'label': 'LIABILITIES', 'type': 'Liability', 'credit_positive': True,  'divisions': ['Current', 'Non-Current']},
    {'key': 'equity',      'label': 'EQUITY',      'type': 'Equity',    'credit_positive': True,  'divisions': None},
]


def rollup(rows, accounts):
    """Group contributing leaf rows under their top-level ancestor account.

    rows: [{'account_id','code','name','amount'}]; accounts: all active Account rows.
    Returns [{'code','name','account_id','total','children':[...]}] sorted by code.
    A leaf whose top-level ancestor is itself becomes a single line, children=[].
    """
    by_id = {a.id: a for a in accounts}

    def top_ancestor(acc):
        seen = set()
        while acc.parent_id and acc.parent_id in by_id and acc.id not in seen:
            seen.add(acc.id)
            acc = by_id[acc.parent_id]
        return acc

    groups = {}
    for r in rows:
        acc = by_id.get(r['account_id'])
        top = top_ancestor(acc) if acc else None
        gid = top.id if top else r['account_id']
        gcode = top.code if top else r['code']
        gname = top.name if top else r['name']
        g = groups.setdefault(gid, {'code': gcode, 'name': gname, 'account_id': gid,
                                    'total': 0.0, 'children': []})
        g['total'] = round(g['total'] + r['amount'], 2)
        if not (top and top.id == r['account_id']):
            g['children'].append({'code': r['code'], 'name': r['name'],
                                  'account_id': r['account_id'], 'amount': r['amount']})
    out = sorted(groups.values(), key=lambda x: x['code'] or '')
    for g in out:
        g['children'].sort(key=lambda c: c['code'] or '')
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_report_sections.py -q -o addopts=""`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/sections.py tests/unit/test_report_sections.py
git commit -m "feat(reports): declarative IS/BS section tables + parent rollup"
```

---

### Task 3: Type-driven Income Statement generator

**Files:**
- Modify: `app/reports/financial.py` (replace `_pl_role`, `_PL_*`, `generate_income_statement`)
- Test: `tests/unit/test_income_statement_generator.py` (rewrite assertions to new behavior)

**Interfaces:**
- Consumes: `IS_SECTIONS`, `rollup` (Task 2); `BASE_CATEGORY` (Task 1).
- Produces: `generate_income_statement(start_date, end_date, branch_id=None) -> dict` with keys `period_start`, `period_end`, `sections` (each `{'key','label','sign','total','lines'}` where `lines` come from `rollup`), and floats `net_sales`, `gross_profit`, `operating_income`, `income_before_tax`, `net_income`.

- [ ] **Step 1: Rewrite the generator test to the new taxonomy**

Replace the body of `tests/unit/test_income_statement_generator.py` `_full_pl` helper to use the new types, and update label/subtotal assertions:

```python
def _full_pl(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash', 'Asset', 'credit')  # normal_balance irrelevant to IS
    sales = _acct('40101', 'Sales - Goods', 'Revenue', 'credit')
    disc  = _acct('40104', 'Sales Discounts', 'Contra-Revenue', 'debit')
    cogs  = _acct('50101', 'Cost of Goods Sold', 'Cost of Goods Sold', 'debit')
    sell  = _acct('50211', 'Sales Commissions', 'Selling Expense', 'debit')
    admin = _acct('50221', 'Office Salaries', 'Administrative Expense', 'debit')
    oinc  = _acct('40201', 'Interest Income', 'Other Income', 'credit')
    oexp  = _acct('50301', 'Interest Expense', 'Other Expense', 'debit')
    tax   = _acct('50401', 'Income Tax - Current', 'Income Tax Expense', 'debit')
    # Sales 1000, Discounts 100, COGS 400, Selling 50, Admin 150, OtherInc 30, OtherExp 20, Tax 60
    _je(b.id, [(cash, 1000, 0), (sales, 0, 1000)], 'JE-S')
    _je(b.id, [(disc, 100, 0), (cash, 0, 100)], 'JE-D')
    _je(b.id, [(cogs, 400, 0), (cash, 0, 400)], 'JE-C')
    _je(b.id, [(sell, 50, 0), (cash, 0, 50)], 'JE-SE')
    _je(b.id, [(admin, 150, 0), (cash, 0, 150)], 'JE-AE')
    _je(b.id, [(cash, 30, 0), (oinc, 0, 30)], 'JE-OI')
    _je(b.id, [(oexp, 20, 0), (cash, 0, 20)], 'JE-OE')
    _je(b.id, [(tax, 60, 0), (cash, 0, 60)], 'JE-T')
    return b

def test_section_totals_and_labels(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    sec = {x['key']: x for x in s['sections']}
    assert sec['revenue']['label'] == 'Sales'
    assert sec['revenue']['total'] == 1000.0
    assert sec['contra_revenue']['total'] == 100.0
    assert sec['cogs']['label'] == 'Cost of Goods Sold'
    assert sec['cogs']['total'] == 400.0
    assert sec['selling']['total'] == 50.0
    assert sec['admin']['total'] == 150.0
    assert sec['other_income']['total'] == 30.0
    assert sec['other_expense']['total'] == 20.0
    assert sec['income_tax']['total'] == 60.0

def test_subtotals(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    assert s['net_sales'] == 900.0           # 1000 - 100
    assert s['gross_profit'] == 500.0        # 900 - 400
    assert s['operating_income'] == 300.0    # 500 - 50 - 150
    assert s['income_before_tax'] == 310.0   # 300 + 30 - 20
    assert s['net_income'] == 250.0          # 310 - 60

def test_lines_rollup_and_account_id(db_session):
    b = _full_pl(db_session)
    s = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), b.id)
    cogs = next(x for x in s['sections'] if x['key'] == 'cogs')
    assert cogs['lines'][0]['code'] == '50101'
    assert 'account_id' in cogs['lines'][0]
```

Also update `_acct` to accept the lowercase normal balance and pass `classification=None` by default (signature: `_acct(code, name, atype, normal='debit', parent_id=None, classification=None)`), and update `test_zero_activity_accounts_excluded` / `test_missing_income_tax_account_yields_zero_section` to use `'Revenue'`/`'Cost of Goods Sold'`/`'Income Tax Expense'` types (no `40000`/`50100`/`50400` wrappers) — assert the zero-activity account is excluded and `net_income`/`income_before_tax` still compute.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_income_statement_generator.py -q -o addopts=""`
Expected: FAIL — old generator returns prefix-based labels / missing `net_sales`.

- [ ] **Step 3: Replace the generator implementation**

In `app/reports/financial.py`, delete `_pl_role`, `_PL_ROLES`, `_PL_DEFAULT_LABEL`, and the old `generate_income_statement`; add:

```python
from app.reports.sections import IS_SECTIONS, BS_SECTIONS, rollup
from app.accounts.account_types import BASE_CATEGORY

def _period_balance(account_id, start_date, end_date, branch_id):
    branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
    d, c = db.session.query(
        func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
        func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
    ).join(JournalEntry).filter(
        JournalEntry.status == 'posted',
        JournalEntry.entry_type.notin_(['closing', 'closing_reversal']),
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date,
        JournalEntryLine.account_id == account_id,
        *branch_filter
    ).one()
    return Decimal(str(d)), Decimal(str(c))

def generate_income_statement(start_date, end_date, branch_id=None):
    """Hierarchical, type-driven Income Statement for a period.

    Sections and their subtotal chain come from IS_SECTIONS; each account's
    placement is its account_type. Revenue-natured types are credit-positive,
    everything else debit-positive. Returns floats for template/export use.
    'net_income' key/semantics preserved (Balance Sheet + Year-End depend on it).
    """
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    def amount(a):
        d, c = _period_balance(a.id, start_date, end_date, branch_id)
        return float((c - d) if BASE_CATEGORY.get(a.account_type) == 'Revenue' else (d - c))

    sections, running, subtotals = [], Decimal('0.00'), {}
    for spec in IS_SECTIONS:
        rows = []
        sec_total = Decimal('0.00')
        for t in spec['types']:
            for a in by_type.get(t, []):
                amt = amount(a)
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': amt})
                    sec_total += Decimal(str(amt))
        running += spec['sign'] * sec_total
        section = {'key': spec['key'], 'label': spec['label'], 'sign': spec['sign'],
                   'total': float(sec_total), 'lines': rollup(rows, accounts)}
        if spec['subtotal']:
            section['subtotal_label'] = spec['subtotal']
            section['subtotal'] = float(running)
            subtotals[spec['subtotal']] = float(running)
        sections.append(section)

    return {
        'period_start': start_date, 'period_end': end_date, 'sections': sections,
        'net_sales': subtotals.get('Net Sales', 0.0),
        'gross_profit': subtotals.get('Gross Profit', 0.0),
        'operating_income': subtotals.get('Operating Income', 0.0),
        'income_before_tax': subtotals.get('Income Before Tax', 0.0),
        'net_income': subtotals.get('Net Income', 0.0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_income_statement_generator.py -q -o addopts=""`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/unit/test_income_statement_generator.py
git commit -m "feat(reports): type-driven Income Statement generator"
```

---

### Task 4: Type-driven Balance Sheet generator

**Files:**
- Modify: `app/reports/financial.py` (replace `_BS_CATEGORIES`, `generate_balance_sheet`)
- Test: `tests/unit/test_balance_sheet_generator.py` (rewrite for type + classification)

**Interfaces:**
- Consumes: `BS_SECTIONS`, `rollup` (Task 2); `generate_income_statement` + `latest_closed_year_end` (existing).
- Produces: `generate_balance_sheet(as_of_date=None, branch_id=None) -> dict` with `sections` (each `{'key','label','total','divisions':[{'label','total','lines'}]}`; equity has one division labeled `'Equity'`), plus `total_assets`, `total_liabilities`, `total_equity`, `total_liabilities_equity`, `is_balanced`, `difference`.

- [ ] **Step 1: Rewrite the balance-sheet test**

```python
# tests/unit/test_balance_sheet_generator.py — key cases (keep existing _branch/_je helpers; update _acct to take classification)
def test_current_vs_noncurrent_divisions(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'debit', classification='Current')
    mach = _acct('11120', 'Machinery', 'Asset', 'debit', classification='Non-Current')
    ap   = _acct('20101', 'AP - Trade', 'Liability', 'credit', classification='Current')
    loan = _acct('21100', 'Long-term Loan', 'Liability', 'credit', classification='Non-Current')
    cap  = _acct('30101', 'Common Stock', 'Equity', 'credit')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE-1')
    _je(b.id, [(mach, 500, 0), (loan, 0, 500)], 'JE-2')
    _je(b.id, [(cash, 0, 200), (ap, 200, 0)], 'JE-3')  # AP credit 200, cash down 200
    bs = generate_balance_sheet(date(2026, 6, 30), b.id)
    assets = next(s for s in bs['sections'] if s['key'] == 'assets')
    divs = {d['label']: d for d in assets['divisions']}
    assert set(divs) == {'Current Assets', 'Non-Current Assets'}
    assert divs['Current Assets']['total'] == 800.0       # cash 1000 - 200
    assert divs['Non-Current Assets']['total'] == 500.0
    liabs = next(s for s in bs['sections'] if s['key'] == 'liabilities')
    ldivs = {d['label']: d['total'] for d in liabs['divisions']}
    assert ldivs == {'Current Liabilities': 200.0, 'Non-Current Liabilities': 500.0}

def test_balanced(db_session):
    b = _branch()
    cash = _acct('10101', 'Cash on Hand', 'Asset', 'debit', classification='Current')
    cap  = _acct('30101', 'Common Stock', 'Equity', 'credit')
    _je(b.id, [(cash, 1000, 0), (cap, 0, 1000)], 'JE-1')
    bs = generate_balance_sheet(date(2026, 6, 30), b.id)
    assert bs['is_balanced'] is True
    assert bs['total_assets'] == bs['total_liabilities_equity'] == 1000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_balance_sheet_generator.py -q -o addopts=""`
Expected: FAIL — old generator groups by hierarchy/prefix, no `divisions` key.

- [ ] **Step 3: Replace the generator**

```python
# app/reports/financial.py — replace generate_balance_sheet (drop _BS_CATEGORIES; use BS_SECTIONS)
def generate_balance_sheet(as_of_date=None, branch_id=None):
    """Classified, type-driven Balance Sheet. Assets/Liabilities split into
    Current/Non-Current by classification; Equity carries Retained Earnings +
    current-year Net Income. Verifies Assets = Liabilities + Equity."""
    if as_of_date is None:
        as_of_date = date.today()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    by_type = {}
    for a in accounts:
        by_type.setdefault(a.account_type, []).append(a)

    def bal(account_id, credit_positive):
        branch_filter = [JournalEntry.branch_id == branch_id] if branch_id else []
        d, c = db.session.query(
            func.coalesce(func.sum(JournalEntryLine.debit_amount), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_amount), 0),
        ).join(JournalEntry).filter(
            JournalEntry.status == 'posted',
            JournalEntry.entry_date <= as_of_date,
            JournalEntryLine.account_id == account_id,
            *branch_filter
        ).one()
        d, c = Decimal(str(d)), Decimal(str(c))
        return (c - d) if credit_positive else (d - c)

    sections, totals = [], {}
    for spec in BS_SECTIONS:
        accts = by_type.get(spec['type'], [])
        divisions = []
        section_total = Decimal('0.00')
        groups_for = spec['divisions'] or [None]
        for div in groups_for:
            rows = []
            div_total = Decimal('0.00')
            for a in accts:
                if div is not None and a.classification != div:
                    continue
                amt = bal(a.id, spec['credit_positive'])
                if amt != 0:
                    rows.append({'account_id': a.id, 'code': a.code, 'name': a.name, 'amount': float(amt)})
                    div_total += amt
            label = f'{div} {spec["label"].title()}' if div else spec['label'].title()
            divisions.append({'label': label, 'total': float(div_total), 'lines': rollup(rows, accounts)})
            section_total += div_total
        totals[spec['key']] = section_total
        sections.append({'key': spec['key'], 'label': spec['label'],
                         'total': float(section_total), 'divisions': divisions})

    # Net income for the open span added to Equity (unchanged policy)
    from app.year_end.service import latest_closed_year_end
    last_close = latest_closed_year_end(branch_id)
    open_start = date(last_close.year + 1, 1, 1) if last_close else date(1900, 1, 1)
    ni = Decimal(str(generate_income_statement(open_start, as_of_date, branch_id=branch_id)['net_income']))
    equity = next(s for s in sections if s['key'] == 'equity')
    if ni != 0:
        eded = equity['divisions'][0] if equity['divisions'] else None
        line = {'code': '', 'name': 'Net Income (current year)', 'account_id': None,
                'total': float(ni), 'children': []}
        if eded:
            eded['lines'].append(line); eded['total'] = float(Decimal(str(eded['total'])) + ni)
        else:
            equity['divisions'].append({'label': 'Equity', 'total': float(ni), 'lines': [line]})
        equity['total'] = float(Decimal(str(equity['total'])) + ni)
        totals['equity'] += ni

    tle = totals['liabilities'] + totals['equity']
    diff = abs(totals['assets'] - tle)
    return {'as_of_date': as_of_date, 'sections': sections,
            'total_assets': float(totals['assets']),
            'total_liabilities': float(totals['liabilities']),
            'total_equity': float(totals['equity']),
            'total_liabilities_equity': float(tle),
            'is_balanced': bool(diff < Decimal('0.01')), 'difference': float(diff)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_balance_sheet_generator.py -q -o addopts=""`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/unit/test_balance_sheet_generator.py
git commit -m "feat(reports): type-driven Balance Sheet with Current/Non-Current divisions"
```

---

### Task 5: Type-driven Cash Flow buckets

**Files:**
- Modify: `app/reports/financial.py` (`_direct_activity` / activity bucketing in `generate_cash_flow`)
- Test: `tests/unit/test_cash_flow_generator.py` (add/adjust a bucketing test)

**Interfaces:**
- Consumes: `account_type` + `classification`.
- Produces: unchanged `generate_cash_flow(start, end, branch_id, method='indirect')` signature and return keys; only the internal account→activity classification changes.

- [ ] **Step 1: Write/adjust the failing test**

```python
# tests/unit/test_cash_flow_generator.py
import pytest
from datetime import date
from app.reports.financial import _activity_bucket   # new helper
from app.accounts.models import Account
pytestmark = [pytest.mark.unit]

def _a(code, atype, name='x', cls=None):
    return Account(code=code, name=name, account_type=atype, classification=cls, normal_balance='debit')

def test_activity_bucket_by_type_and_classification():
    assert _activity_bucket(_a('11120', 'Asset', 'Machinery', 'Non-Current')) == 'investing'
    assert _activity_bucket(_a('11131', 'Asset', 'Accumulated Depreciation - Machinery', 'Non-Current')) == 'operating'
    assert _activity_bucket(_a('21100', 'Liability', 'Long-term Loan', 'Non-Current')) == 'financing'
    assert _activity_bucket(_a('30101', 'Equity', 'Common Stock')) == 'financing'
    assert _activity_bucket(_a('10201', 'Asset', 'AR - Trade', 'Current')) == 'operating'
    assert _activity_bucket(_a('20101', 'Liability', 'AP - Trade', 'Current')) == 'operating'
    assert _activity_bucket(_a('50101', 'Cost of Goods Sold', 'COGS')) == 'operating'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_cash_flow_generator.py -q -o addopts=""`
Expected: FAIL — `_activity_bucket` not defined.

- [ ] **Step 3: Add the helper and use it**

Add near the other CF helpers in `financial.py`, replacing prefix-based `_direct_activity`’s classification logic with:

```python
def _activity_bucket(account):
    """Cash-flow activity for a non-cash account, by type + classification.
    Investing: Non-Current Assets (excl. accumulated depreciation by name).
    Financing: Non-Current Liabilities + all Equity. Operating: everything else."""
    t, cls = account.account_type, account.classification
    if t == 'Asset' and cls == 'Non-Current' and not _is_depreciation_name(account):
        return 'investing'
    if (t == 'Liability' and cls == 'Non-Current') or t == 'Equity':
        return 'financing'
    return 'operating'
```

Then update `generate_cash_flow` to call `_activity_bucket(account)` wherever it previously called `_direct_activity(account)` (replace the prefix checks). Keep `_is_cash` and `_is_depreciation_name` (name-based) unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_cash_flow_generator.py tests/integration/test_cash_flow_views.py -q -o addopts=""`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/financial.py tests/unit/test_cash_flow_generator.py
git commit -m "feat(reports): type-driven Cash Flow activity buckets"
```

---

### Task 6: Update Excel exporters to the new section shapes

**Files:**
- Modify: `app/reports/statement_export.py` (`build_income_statement_xlsx`, `balance_sheet_lines`/`build_balance_sheet_xlsx`, `cash_flow_lines`/`build_cash_flow_xlsx` as needed)
- Test: `tests/unit/test_income_statement_export.py` (new), update `tests/unit/test_cash_flow_export.py` if line labels move

**Interfaces:**
- Consumes: the new generator return shapes (Tasks 3–4).
- Produces: xlsx byte builders unchanged in signature; internal row mapping follows `sections[].lines[]` (IS) and `sections[].divisions[].lines[]` (BS).

- [ ] **Step 1: Write a failing exporter test (IS)**

```python
# tests/unit/test_income_statement_export.py
import pytest
from io import BytesIO
from openpyxl import load_workbook
from datetime import date
from app.reports.financial import generate_income_statement
from app.reports.statement_export import build_income_statement_xlsx
pytestmark = [pytest.mark.unit]

def test_is_xlsx_has_subtotal_rows(db_session):
    # reuse the generator test's _full_pl via a minimal inline build, or seed two accounts
    # (kept short: assert the workbook opens and contains the Net Income label)
    data = generate_income_statement(date(2026, 6, 1), date(2026, 6, 30), None)
    xlsx = build_income_statement_xlsx(data, company='ABC', branch='Main')
    wb = load_workbook(BytesIO(xlsx))
    cells = [c.value for row in wb.active.iter_rows() for c in row]
    assert 'Net Income' in cells
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_income_statement_export.py -q -o addopts=""`
Expected: FAIL — builder reads old keys / `KeyError`.

- [ ] **Step 3: Update the exporters**

Rewrite the IS builder to iterate `data['sections']`, emitting per section: the section label row, each `line` (group total) with indented `children`, and a subtotal row when `section.get('subtotal_label')`. Rewrite the BS builder to iterate `sections[].divisions[].lines[]` with division subtotals and the existing TOTAL ASSETS / TOTAL LIABILITIES AND EQUITY rows. Keep accounting number formats, bold section/subtotal rows, gridlines off (existing helpers). Cash-flow builder only changes if line labels changed (they did not).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_income_statement_export.py tests/unit/test_cash_flow_export.py -q -o addopts=""`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/reports/statement_export.py tests/unit/test_income_statement_export.py
git commit -m "feat(reports): Excel exporters follow type-driven section shapes"
```

---

### Task 7: Account form — rich type choices + conditional classification

**Files:**
- Modify: `app/accounts/forms.py` (type `SelectField` choices, add `classification` field), `app/accounts/views.py` (normal-balance defaulting via `DEFAULT_NORMAL_BALANCE`, require classification for Asset/Liability), `app/accounts/templates/accounts/form.html` (classification select + progressive disclosure JS)
- Test: `tests/integration/test_account_form_types.py` (new)

**Interfaces:**
- Consumes: `ACCOUNT_TYPES`, `CLASSIFICATIONS`, `TYPES_NEEDING_CLASSIFICATION`, `DEFAULT_NORMAL_BALANCE` (Task 1).
- Produces: account create/edit accepting the 11 types; persists `classification` for Asset/Liability.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_account_form_types.py
import pytest
from app.accounts.models import Account
pytestmark = [pytest.mark.integration]

def login(client): client.post('/login', data={'username':'admin','password':'admin123'}, follow_redirects=True)

def test_create_cogs_account(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post('/accounts/create', data={
        'code':'50101','name':'Cost of Goods Sold','account_type':'Cost of Goods Sold',
        'classification':'', 'description':''}, follow_redirects=True)
    assert resp.status_code == 200
    a = Account.query.filter_by(code='50101').first()
    assert a and a.account_type == 'Cost of Goods Sold'
    assert a.normal_balance == 'debit'           # defaulted from type

def test_asset_requires_classification(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.post('/accounts/create', data={
        'code':'10199','name':'Some Asset','account_type':'Asset','classification':'','description':''},
        follow_redirects=True)
    assert Account.query.filter_by(code='10199').first() is None  # rejected: missing classification

def test_asset_with_classification_persists(client, db_session, admin_user, main_branch):
    login(client)
    client.post('/accounts/create', data={
        'code':'10199','name':'Some Asset','account_type':'Asset','classification':'Current','description':''},
        follow_redirects=True)
    a = Account.query.filter_by(code='10199').first()
    assert a.classification == 'Current' and a.normal_balance == 'debit'
```

(Confirm the create route path with `app/accounts/views.py`; adjust `/accounts/create` if different.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_account_form_types.py -q -o addopts=""`
Expected: FAIL — type choices reject new values / classification not enforced.

- [ ] **Step 3: Implement form + view + template**

- `forms.py`: set `account_type` choices from `[(t, t) for t in ACCOUNT_TYPES]` (optionally grouped); add `classification = SelectField('Classification', choices=[('','—'),('Current','Current'),('Non-Current','Non-Current')], validators=[Optional()])`.
- `views.py` (create & edit): if `account_type in TYPES_NEEDING_CLASSIFICATION` and no classification → flash error + re-render; else set `classification` (null for non-BS types). Default `normal_balance = DEFAULT_NORMAL_BALANCE[account_type]` unless the form supplies an explicit override.
- `form.html`: render the classification select; add a small inline script that shows it only when `account_type` is Asset/Liability (progressive disclosure). Bump the form template's static `?v=N` if it links a shared asset.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_account_form_types.py -q -o addopts=""`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/accounts/forms.py app/accounts/views.py app/accounts/templates/accounts/form.html tests/integration/test_account_form_types.py
git commit -m "feat(accounts): rich type choices + conditional Current/Non-Current"
```

---

### Task 8: Account-ledger drill-down endpoint

**Files:**
- Modify: `app/reports/views.py` (add `account_ledger_json` route)
- Test: `tests/integration/test_account_ledger_endpoint.py` (new)

**Interfaces:**
- Produces: `GET /reports/account-ledger?account_id=<id>&start=<YYYY-MM-DD>&end=<YYYY-MM-DD>` → JSON `{'account':{'code','name'}, 'lines':[{'date','source','particulars','debit','credit','balance'}], 'opening':float, 'closing':float}`. `@login_required`. Reuses the existing General Ledger query helper if present; else inline the posted-line query (exclude unposted).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_account_ledger_endpoint.py
import pytest
from datetime import date
pytestmark = [pytest.mark.integration]

def login(client): client.post('/login', data={'username':'admin','password':'admin123'}, follow_redirects=True)

def test_account_ledger_json(client, db_session, admin_user, main_branch):
    from app import db
    from app.accounts.models import Account
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from decimal import Decimal
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   classification='Current', normal_balance='debit', is_active=True)
    rev = Account(code='40101', name='Sales', account_type='Revenue', normal_balance='credit', is_active=True)
    db.session.add_all([cash, rev]); db.session.commit()
    je = JournalEntry(entry_number='JE-1', entry_date=date(2026,6,10), description='d',
                      reference='JE-1', entry_type='adjustment', branch_id=main_branch.id,
                      status='posted', is_balanced=True, total_debit=Decimal('100'), total_credit=Decimal('100'))
    db.session.add(je); db.session.flush()
    db.session.add_all([
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash.id, debit_amount=Decimal('100'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=rev.id, debit_amount=Decimal('0'), credit_amount=Decimal('100'))])
    db.session.commit()
    login(client)
    resp = client.get(f'/reports/account-ledger?account_id={cash.id}&start=2026-06-01&end=2026-06-30')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['account']['code'] == '10101'
    assert len(data['lines']) == 1
    assert data['lines'][0]['debit'] == 100.0
    assert data['closing'] == 100.0

def test_account_ledger_requires_login(client, db_session):
    resp = client.get('/reports/account-ledger?account_id=1&start=2026-06-01&end=2026-06-30')
    assert resp.status_code in (302, 401)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_account_ledger_endpoint.py -q -o addopts=""`
Expected: FAIL — 404 (route absent).

- [ ] **Step 3: Implement the route**

Add to `app/reports/views.py` a `@login_required` route building opening balance (sum of posted lines before `start`) and per-line running balance for the account over `[start,end]`, signed by the account's `normal_balance`. Return the JSON shape above.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_account_ledger_endpoint.py -q -o addopts=""`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/reports/views.py tests/integration/test_account_ledger_endpoint.py
git commit -m "feat(reports): account-ledger JSON endpoint for FS drill-down"
```

---

### Task 9: FS templates — roll-up lines + expandable composition + ledger modal

**Files:**
- Modify: `app/reports/templates/reports/income_statement.html`, `balance_sheet.html`, `cash_flow.html`
- Create: `app/reports/templates/reports/_ledger_modal.html` (shared partial)
- Modify/Create: `app/static/js/fs-drilldown.js`, CSS in `app/static/css/style.css` (tokens only)
- Test: browser verification (manual via Playwright) + an integration assertion that each statement page renders the new structure

**Interfaces:**
- Consumes: generator outputs (Tasks 3–4–5), `/reports/account-ledger` (Task 8).

- [ ] **Step 1: Write a failing render assertion**

```python
# append to tests/integration/test_income_statement_views.py
def test_is_page_shows_subtotal_and_drilldown_hooks(client, db_session, admin_user, main_branch):
    client.post('/login', data={'username':'admin','password':'admin123'}, follow_redirects=True)
    resp = client.get('/reports/income-statement')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Net Income' in html
    assert 'data-account-id' in html        # drill-down hook present on lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_income_statement_views.py -q -o addopts=""`
Expected: FAIL — no `data-account-id` hooks yet.

- [ ] **Step 3: Implement templates + JS + CSS**

- Each statement template iterates `sections` → group `lines` as one row each (code + name + total), with an expander toggling the `children` sub-rows (pure CSS/JS, collapsed by default). Render subtotal rows where present. Each clickable line carries `data-account-id`, `data-start`, `data-end` (IS/CF) or `data-asof` (BS).
- `_ledger_modal.html`: a hidden modal shell (design tokens, no `confirm()`); included by all three statements.
- `fs-drilldown.js`: delegate click on `[data-account-id]` → fetch `/reports/account-ledger` → populate + show the modal; Esc/backdrop closes. Link with `?v=1`; bump if edited later.

- [ ] **Step 4: Verify (targeted test + browser)**

Run: `python -m pytest tests/integration/test_income_statement_views.py -q -o addopts=""` → PASS.
Browser: `/run`, log in, open Income Statement and Balance Sheet, expand a group, click a line → ledger modal shows entries; confirm BS Current/Non-Current divisions render and the statement reconciles.

- [ ] **Step 5: Commit**

```bash
git add app/reports/templates/reports/ app/static/js/fs-drilldown.js app/static/css/style.css tests/integration/test_income_statement_views.py
git commit -m "feat(reports): roll-up FS lines with expandable composition + ledger drill-down modal"
```

---

### Task 10: Re-type the manufacturing COA (cas_demo.db)

**Files:**
- Create: `scripts/retype_manufacturing_coa.py` (one-off, current DB only)
- Test: `tests/unit/test_manufacturing_coa_types.py` (asserts invariants on the produced data via a fixture-built COA, not the live DB)

**Interfaces:**
- Consumes: `ACCOUNT_TYPES`, `CLASSIFICATIONS`.

- [ ] **Step 1: Write the invariant test**

```python
# tests/unit/test_manufacturing_coa_types.py
import pytest
from app.accounts.account_types import ACCOUNT_TYPES, TYPES_NEEDING_CLASSIFICATION
pytestmark = [pytest.mark.unit]

def test_retype_map_is_valid():
    from scripts.retype_manufacturing_coa import TYPE_BY_CODE, CLASS_BY_CODE
    for code, t in TYPE_BY_CODE.items():
        assert t in ACCOUNT_TYPES, (code, t)
        if t in TYPES_NEEDING_CLASSIFICATION:
            assert CLASS_BY_CODE.get(code) in ('Current', 'Non-Current'), code
        else:
            assert code not in CLASS_BY_CODE, code
    # required posting codes keep their base meaning
    assert TYPE_BY_CODE['10201'] == 'Asset' and TYPE_BY_CODE['20101'] == 'Liability'
    assert TYPE_BY_CODE['30201'] == 'Equity' and TYPE_BY_CODE['30301'] == 'Equity'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_manufacturing_coa_types.py -q -o addopts=""`
Expected: FAIL — `scripts.retype_manufacturing_coa` absent.

- [ ] **Step 3: Write the script**

Create `scripts/retype_manufacturing_coa.py` defining `TYPE_BY_CODE` and `CLASS_BY_CODE` for the 146-account COA (drop the 10 wrapper codes; promote natural groups to top-level by setting `parent_id=None`; assign types/classifications per the spec's "Chart of Accounts re-typing" section), plus a `main()` (guarded by `if __name__ == '__main__':`) that, within `app.app_context()`: deletes the 10 wrapper accounts, re-parents their children to top-level, sets `account_type`/`classification`/`normal_balance` per the maps, leaves VAT FKs intact, and prints a verification summary (counts per type, required-code check, BS/IS/CF generators run without error).

- [ ] **Step 4: Run test + execute the script**

Run: `python -m pytest tests/unit/test_manufacturing_coa_types.py -q -o addopts=""` → PASS.
Then (current DB only): `PYTHONPATH=. python scripts/retype_manufacturing_coa.py` and confirm the printed summary: 146 accounts, every account_type in the taxonomy, all Assets/Liabilities classified, the three generators return without exception.

- [ ] **Step 5: Commit**

```bash
git add scripts/retype_manufacturing_coa.py tests/unit/test_manufacturing_coa_types.py
git commit -m "feat(accounts): re-type manufacturing COA to FS taxonomy (cas_demo)"
```

---

### Task 11: Cross-app blast-radius sweep + verification

**Files:**
- Modify: any site found referencing removed symbols (`_pl_role`, `_PL_*`, `_BS_CATEGORIES`, `_direct_activity`) or assuming 5-value `account_type` (`app/dashboard/dashboard_data.py`, `app/accounts/templates/accounts/list.html`/`detail.html` badges)
- Test: targeted re-runs of affected suites

- [ ] **Step 1: Grep for removed/legacy symbols**

Run (report only): `git grep -nE "_pl_role|_PL_ROLES|_PL_DEFAULT_LABEL|_BS_CATEGORIES|_direct_activity" app/`
Expected after Tasks 3–5: only definitions/uses inside `financial.py` you intend; fix any stragglers (templates/exports).
Run: `git grep -nE "account_type\s*(==|!=| in | not in )" app/` and confirm each remaining check still holds under the new taxonomy or routes through `base_category`.

- [ ] **Step 2: Fix any stragglers**

Update found sites (e.g. dashboard groupings, list/detail badge color maps) to use `account_type`/`base_category` correctly. Show the exact edit per site.

- [ ] **Step 3: Run the affected suites**

Run: `python -m pytest tests/unit/test_account_types.py tests/unit/test_report_sections.py tests/unit/test_income_statement_generator.py tests/unit/test_balance_sheet_generator.py tests/unit/test_cash_flow_generator.py tests/integration/test_income_statement_views.py tests/integration/test_balance_sheet_views.py tests/integration/test_cash_flow_views.py tests/integration/test_trial_balance_views.py tests/integration/test_account_form_types.py tests/integration/test_account_ledger_endpoint.py tests/integration/test_year_end_close.py -q -o addopts=""`
Expected: PASS (Year-End included because BS/IS feed it).

- [ ] **Step 4: Browser smoke**

`/run`, log in as admin, open Income Statement / Balance Sheet / Cash Flow / Trial Balance against the re-typed COA; verify each renders, the BS balances, divisions and subtotals are correct, and the ledger drill-down works from each statement.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(reports): blast-radius sweep for type-driven FS"
```

---

## Self-Review

**Spec coverage:**
- Enrich `account_type` + `classification` + `base_category` → Task 1. ✔
- Dynamic IS (declarative sections, Net Sales/Gross Profit/Operating Income/Income Before Tax/Net Income, contra-revenue netting, income-tax line) → Tasks 2–3. ✔
- Dynamic BS (Current/Non-Current divisions, equity RE+NI) → Tasks 2–4. ✔
- Dynamic CF (type/classification buckets) → Task 5. ✔
- Excel exporters follow new shapes → Task 6. ✔
- Account form rich types + conditional classification + normal-balance default → Task 7. ✔
- Roll-up parent lines + expandable composition → Tasks 2 (helper), 9 (UI). ✔
- Click-line → ledger modal → Tasks 8 (endpoint) + 9 (modal/JS). ✔
- COA re-typing, drop wrappers, preserve posting codes → Task 10. ✔
- Blast radius (financial.py, statement_export.py, accounts, dashboard, posting, tests) → Tasks 6,7,11. ✔

**Placeholder scan:** Task 6 Step 3, Task 8 Step 3, Task 9 Step 3, Task 10 Step 3 describe edits prose-style but each names exact files, the data shape to iterate, and an accompanying test with concrete assertions that pins the behavior; no "TBD"/"handle edge cases" left. Generators/helpers/endpoint show full code.

**Type consistency:** Generator returns use `sections[].lines[]` (IS) and `sections[].divisions[].lines[]` (BS) consistently; `rollup` returns `{code,name,account_id,total,children[]}` used by exporters (Task 6) and templates (Task 9); `_activity_bucket` name consistent across Task 5 test/impl/Task 11 grep; `DEFAULT_NORMAL_BALANCE` lowercase values consistent with Global Constraints.
