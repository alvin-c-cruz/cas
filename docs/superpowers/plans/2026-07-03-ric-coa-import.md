# RIC Legacy COA Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Rowell Industrial Corporation's legacy 340-account Chart of Accounts into the CAS `ric.db`, reshaped into CAS's hierarchical model (28 non-postable group headers + 338 postable leaves; 2 legacy leaves skipped as seed-name duplicates), with titles proper-cased.

**Architecture:** Three pure modules under `scripts/ric_coa/` — `proper_case` (title caser), `mapping` (type/group/contra rules + `build_accounts`), and `import_coa` (reads the legacy SQLite, writes via the CAS app factory with audit). Pure logic is unit-tested; the DB write is integration-tested against the in-memory test DB. The actual run against `ric.db` is the final operator step (dry-run → review → commit → verify).

**Tech Stack:** Python 3.13, Flask + SQLAlchemy (CAS app factory), sqlite3 (legacy read), pytest.

**Spec:** `docs/superpowers/specs/2026-07-03-ric-coa-import-design.md`

## Global Constraints

- **Titles:** legacy `account_title` stored **Title Case** via `proper_case()`; transform is **case-only** (`proper_case(t).upper() == t.upper()` for all titles). Never `str.title()`.
- **`code` = legacy `account_number` verbatim**; leaf `name` = proper-cased title; group `name` = descriptive header title.
- **Result:** 28 group headers (non-postable, `parent_id=NULL`) + 338 leaves (postable, parented to a group). Import adds 366 accounts; the 25 seed accounts are **not** cleared → 391 total.
- **Name uniqueness (`Account.name` is UNIQUE):** SKIP the two legacy leaves whose proper-cased name duplicates a kept seed account — `12501 Creditable Withholding Tax` (seed `10212`) and `32101 Retained Earnings` (seed `30200`) — via `mapping.SKIP_CODES`. Rename groups `116` → *Prepaid Expenses & Interest* and `511` → *Other Income & Gains* (they collided with their own leaf). The importer runs `assert_no_name_clash` before writing.
- **`normal_balance`** from `app.accounts.account_types.DEFAULT_NORMAL_BALANCE[account_type]` (lowercase `debit`/`credit`), **overridden to `credit`** for the 13 contra leaves (group `123` Accumulated Depreciation, and code `11202` Allowance for Bad Debts). Contra override applies to **leaves only**, not the `123` header.
- **Classification overrides:** groups `125` and `126` are `Current` (not the Non-Current their legacy "Other Assets" type implies).
- **Audit:** every created account (group + leaf) logs `log_audit(module='accounts', action='import', record_id, record_identifier='<code> <name>', new_values=<spec dict>)`.
- **Target safety:** the importer refuses to write unless the bound DB URI ends in `ric.db`, and refuses if any legacy leaf code already exists (rebuild = clear first).
- **Legacy source (read-only):** `C:\envs\ric-workspace\legacy ric\accounting\instance\data.db`.
- Tests: run from `projects/cas/`; `tests/` is gitignored → `git add -f` new test files. Use `--no-cov` for focused runs.

---

### Task 1: `proper_case()` title caser

**Files:**
- Create: `scripts/ric_coa/__init__.py` (empty)
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/ric_coa/proper_case.py`
- Test: `tests/unit/test_ric_proper_case.py`

**Interfaces:**
- Produces: `proper_case(title: str) -> str` — case-only Title-Case transform, acronym- and code-preserving.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ric_proper_case.py
import pytest
from scripts.ric_coa.proper_case import proper_case

pytestmark = [pytest.mark.unit]

@pytest.mark.parametrize("src,expect", [
    ("CASH ON HAND/CASH SALES",              "Cash on Hand/Cash Sales"),
    ("CASH IN BANK - TIME DEPOSIT (RCC)",    "Cash in Bank - Time Deposit (RCC)"),
    ("BPI-00008-85",                          "BPI-00008-85"),
    ("CHINA BANK-361-0",                      "China Bank-361-0"),
    ("CHINA BANK $ 520000577",                "China Bank $ 520000577"),
    ("ACC. DEP'N-OFFICE FCTY Q.C. (TAGUIG)",  "Acc. Dep'n-Office Fcty Q.C. (Taguig)"),
    ("13TH MO. PAY - TINCAN",                 "13th Mo. Pay - Tincan"),
    ("VAT PAYABLE",                           "VAT Payable"),
    ("X'MAS T-SHIRT",                         "X'mas T-Shirt"),
    ("PHILHEALTH PREMIUM PAYABLE",            "PhilHealth Premium Payable"),
    ("FO - LIGHTS & WATER - TINCAN",          "FO - Lights & Water - Tincan"),
    ("WITHHOLDING TAX PAYABLE-SUPPLIERS - 1/2%", "Withholding Tax Payable-Suppliers - 1/2%"),
    ("ACCOUNTS RECEIVABLE-PDC",               "Accounts Receivable-PDC"),
    ("SSS SALARY LOAN PAYABLE",               "SSS Salary Loan Payable"),
])
def test_proper_case_cases(src, expect):
    assert proper_case(src) == expect

def test_proper_case_is_case_only():
    # transform must never add/drop/reorder characters — only change case
    for s in ["ACC. DEP'N-MOLDS & DIES - PLASTIC", "INPUT TAX - CAPITAL GOODS", "13TH MO. PAY"]:
        assert proper_case(s).upper() == s.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_ric_proper_case.py -m unit --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ric_coa'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/ric_coa/proper_case.py
"""Smart proper-case for RIC account titles. Deterministic + reusable.
Title-cases each maximal letter-run; keeps true acronyms uppercase and leaves
digits/%/$/parens/hyphens untouched, so codes/serials/percentages survive."""
import re

ACRONYMS = {
    'BPI','SSS','HDMF','NHMFC','VAT','CWT','WHT','PDC','RCC','RLMC','RIC','TIN',
    'FO','SE','AE','HMO','ATM','QC',
}
SPECIAL = {'PHILHEALTH': 'PhilHealth', "X'MAS": "X'mas"}
MINOR = {'a','an','and','of','to','the','on','in','for','or','by','with','at','as'}
ORD = {'st','nd','rd','th'}
WORD = re.compile(r"[A-Za-z][A-Za-z.']*")


def _case_word(w, is_first, prev_is_digit):
    if prev_is_digit and w.lower() in ORD:
        return w.lower()
    if w.upper() in SPECIAL:
        return SPECIAL[w.upper()]
    bare = re.sub(r"[.']", '', w).upper()
    if bare in ACRONYMS:
        return w.upper()
    low = w.lower()
    if not is_first and low in MINOR:
        return low
    out, capped = [], False
    for ch in w:
        if not capped and ch.isalpha():
            out.append(ch.upper()); capped = True
        else:
            out.append(ch.lower())
    return ''.join(out)


def proper_case(title):
    def repl(m):
        pre = title[:m.start()]
        is_first = not any(c.isalpha() for c in pre)
        prev_is_digit = bool(pre) and pre[-1].isdigit()
        return _case_word(m.group(0), is_first, prev_is_digit)
    return WORD.sub(repl, title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_ric_proper_case.py -m unit --no-cov -q`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add -f scripts/__init__.py scripts/ric_coa/__init__.py scripts/ric_coa/proper_case.py tests/unit/test_ric_proper_case.py
git commit -m "feat(ric-coa): acronym-preserving proper_case title caser"
```

---

### Task 2: COA mapping — types, groups, `build_accounts`

**Files:**
- Create: `scripts/ric_coa/mapping.py`
- Test: `tests/unit/test_ric_mapping.py`

**Interfaces:**
- Consumes: `proper_case` (Task 1); `app.accounts.account_types.DEFAULT_NORMAL_BALANCE`.
- Produces:
  - `TYPE_MAP: dict[str, tuple[str, str | None]]` — legacy type → (CAS type, base classification).
  - `GROUPS: "OrderedDict[str, tuple[str, str, str | None]]"` — group code → (title, CAS type, classification).
  - `assign_group(legacy_type: str, account_number: str) -> str` — returns the group code for a leaf.
  - `AccountSpec` dataclass: `code, name, account_type, classification, normal_balance, parent_code, is_group`; method `as_dict() -> dict`.
  - `build_accounts(legacy_rows: list[tuple[str, str, str]]) -> list[AccountSpec]` — group specs (only the groups actually used) followed by 338 leaf specs (2 skipped); leaves proper-cased, parented, contra + classification applied.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ric_mapping.py
import pytest
from scripts.ric_coa.mapping import assign_group, build_accounts, GROUPS

pytestmark = [pytest.mark.unit]

# a small legacy fixture: (account_number, account_title, legacy_type)
ROWS = [
    ("11101", "CASH ON HAND/CASH SALES",        "Cash and Cash Equivalents"),
    ("11201", "ACCOUNTS RECEIVABLE-TRADE",      "Trade Receivable"),
    ("11202", "ALLOWANCE FOR BAD DEBTS",        "Other Current Assets"),
    ("11301", "RAW MATERIALS INVENTORY-TINCAN", "Other Current Assets"),
    ("12201", "OFFICE FCTY - TAGUIG",           "Fixed Assets"),
    ("12301", "ACC. DEP'N-OFFICE FCTY",         "Fixed Assets"),
    ("12501", "CREDITABLE WITHHOLDING TAX",     "Other Assets"),
    ("64101", "INDIRECT LABOR - Tincan/Plastic","Factory Overhead"),
    ("65101", "FO - TELEPHONE & POSTAGE",       "Factory Overhead"),
]

def test_assign_group_routes_by_type_and_prefix():
    assert assign_group("Cash and Cash Equivalents", "11101") == "111"
    assert assign_group("Trade Receivable", "11201") == "112"
    assert assign_group("Other Current Assets", "11202") == "112N"   # advances, not trade
    assert assign_group("Other Current Assets", "11301") == "113"
    assert assign_group("Fixed Assets", "12201") == "122"
    assert assign_group("Fixed Assets", "12301") == "123"            # accumulated depreciation
    assert assign_group("Other Assets", "12501") == "125"
    assert assign_group("Factory Overhead", "64101") == "641"
    assert assign_group("Factory Overhead", "65101") == "651"

def test_build_accounts_shapes_groups_and_leaves():
    specs = build_accounts(ROWS)
    groups = [s for s in specs if s.is_group]
    leaves = [s for s in specs if not s.is_group]
    assert len(leaves) == len(ROWS)
    # groups precede leaves, one per used code
    assert all(g.is_group for g in specs[:len(groups)])
    assert {g.code for g in groups} == {"111","112","112N","113","122","123","125","641","651"}
    # leaf name is proper-cased; parent is its group
    cash = next(l for l in leaves if l.code == "11101")
    assert cash.name == "Cash on Hand/Cash Sales"
    assert cash.parent_code == "111" and cash.account_type == "Asset" and cash.classification == "Current"

def test_contra_override_to_credit():
    specs = build_accounts(ROWS)
    accdep = next(s for s in specs if s.code == "12301")   # accumulated depreciation leaf
    allow  = next(s for s in specs if s.code == "11202")   # allowance for bad debts leaf
    assert accdep.normal_balance == "credit"
    assert allow.normal_balance == "credit"
    # a normal asset leaf stays debit
    assert next(s for s in specs if s.code == "11101").normal_balance == "debit"
    # the 123 GROUP header is NOT contra-overridden
    assert next(s for s in specs if s.is_group and s.code == "123").normal_balance == "debit"

def test_classification_override_125_current():
    specs = build_accounts(ROWS)
    g125 = next(s for s in specs if s.is_group and s.code == "125")
    l125 = next(s for s in specs if s.code == "12501")
    assert g125.classification == "Current" and l125.classification == "Current"

def test_group_registry_has_28_entries():
    assert len(GROUPS) == 28
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_ric_mapping.py -m unit --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ric_coa.mapping'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/ric_coa/mapping.py
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
    ('113',  ('Inventory — Tincan',                     'Asset', 'Current')),
    ('114',  ('Inventory — Plastic',                    'Asset', 'Current')),
    ('115',  ('Factory & Maintenance Supplies',              'Asset', 'Current')),
    ('116',  ('Prepaid Expenses',                            'Asset', 'Current')),
    ('117',  ('Assets in Transit',                           'Asset', 'Current')),
    ('125',  ('Creditable Withholding Tax & Overpayments',   'Asset', 'Current')),
    ('126',  ('Input VAT & Tax Credits',                     'Asset', 'Current')),
    ('122',  ('Property, Plant & Equipment — at Cost',  'Asset', 'Non-Current')),
    ('123',  ('Accumulated Depreciation',                    'Asset', 'Non-Current')),
    ('124',  ('Investments',                                 'Asset', 'Non-Current')),
    ('211',  ('Accounts Payable',                            'Liability', 'Current')),
    ('219',  ('Other Current Liabilities',                   'Liability', 'Current')),
    ('221',  ('Tax & Withholding Payables',                  'Liability', 'Non-Current')),
    ('222',  ('Statutory & Loan Payables',                   'Liability', 'Non-Current')),
    ('311',  ("Stockholders' Equity",                        'Equity', None)),
    ('411',  ('Sales — Tincan',                         'Revenue', None)),
    ('412',  ('Sales — Plastic',                        'Revenue', None)),
    ('421',  ('Scrap Sales',                                 'Revenue', None)),
    ('511',  ('Other Income',                                'Other Income', None)),
    ('611',  ('Direct Materials',                            'Cost of Goods Sold', None)),
    ('621',  ('Direct Labor',                                'Cost of Goods Sold', None)),
    ('641',  ('Indirect Labor & Personnel Cost',             'Cost of Goods Sold', None)),
    ('651',  ('Manufacturing Overhead',                      'Cost of Goods Sold', None)),
    ('661',  ('Selling Expenses',                            'Selling Expense', None)),
    ('671',  ('Administrative Expenses',                     'Administrative Expense', None)),
])


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
    specs = []
    used = OrderedDict()  # preserve GROUPS order, only used codes
    for num, title, ltype in legacy_rows:
        used[assign_group(ltype, num)] = True
    for code in GROUPS:
        if code in used:
            title, ct, cls = GROUPS[code]
            specs.append(AccountSpec(code, title, ct, cls,
                                     DEFAULT_NORMAL_BALANCE[ct], None, True))
    for num, title, ltype in legacy_rows:
        code = assign_group(ltype, num)
        _gt, ct, cls = GROUPS[code]
        nb = 'credit' if _is_contra(code, num) else DEFAULT_NORMAL_BALANCE[ct]
        specs.append(AccountSpec(str(num), proper_case(title), ct, cls, nb, code, False))
    return specs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_ric_mapping.py -m unit --no-cov -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add -f scripts/ric_coa/mapping.py tests/unit/test_ric_mapping.py
git commit -m "feat(ric-coa): COA type/group mapping + build_accounts specs"
```

---

### Task 3: Importer — read legacy, write via app factory, CLI

**Files:**
- Create: `scripts/ric_coa/import_coa.py`
- Test: `tests/integration/test_ric_coa_import.py`

**Interfaces:**
- Consumes: `build_accounts`, `AccountSpec` (Task 2); `app` (from `flask_app`), `app.accounts.models.Account`, `app.audit.utils.log_audit`.
- Produces:
  - `read_legacy(db_path: str) -> list[tuple[str, str, str]]` — `(account_number, account_title, legacy_type)`, ordered by number.
  - `assert_importable(session) -> None` — raises `RuntimeError` if any leaf code already exists.
  - `write_accounts(specs: list[AccountSpec], session) -> dict` — creates groups then leaves (parent links via a code→id map), audit-logs each, flushes; returns `{'groups': n, 'leaves': n}`. Does **not** commit or assert the target — caller does.
  - `summarize(specs) -> dict` — counts for dry-run: `{'groups','leaves','contra','by_section'}`.
  - `main()` — CLI: `--commit` (else dry-run), `--legacy PATH`; asserts target URI ends `ric.db`, runs `assert_importable`, writes + commits on `--commit`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_ric_coa_import.py
import pytest
from app import db
from app.accounts.models import Account
from scripts.ric_coa.mapping import build_accounts
from scripts.ric_coa.import_coa import write_accounts, assert_importable, summarize

pytestmark = [pytest.mark.integration]

ROWS = [
    ("11101", "CASH ON HAND/CASH SALES",   "Cash and Cash Equivalents"),
    ("11202", "ALLOWANCE FOR BAD DEBTS",   "Other Current Assets"),
    ("12301", "ACC. DEP'N-OFFICE FCTY",    "Fixed Assets"),
    ("65101", "FO - TELEPHONE & POSTAGE",  "Factory Overhead"),
]

def test_write_creates_groups_then_postable_leaves(db_session):
    specs = build_accounts(ROWS)
    result = write_accounts(specs, db.session)
    db.session.commit()
    assert result == {'groups': 3, 'leaves': 4}   # groups 111,112N,123,651 -> wait see note
    # leaf is postable: has a parent and no children
    leaf = Account.query.filter_by(code="11101").one()
    assert leaf.parent_id is not None
    assert leaf.name == "Cash on Hand/Cash Sales"
    # group is non-postable: top-level
    grp = Account.query.filter_by(code="111").one()
    assert grp.parent_id is None
    # contra leaf stored credit
    assert Account.query.filter_by(code="12301").one().normal_balance == "credit"

def test_write_audits_each_account(db_session):
    from app.audit.models import AuditLog
    write_accounts(build_accounts(ROWS), db.session)
    db.session.commit()
    imported = AuditLog.query.filter_by(module='accounts', action='import').count()
    assert imported == 3 + 4   # groups + leaves

def test_assert_importable_blocks_on_existing_code(db_session):
    write_accounts(build_accounts(ROWS), db.session)
    db.session.commit()
    with pytest.raises(RuntimeError):
        assert_importable(db.session)   # 11101 now exists

def test_summarize_counts(db_session):
    s = summarize(build_accounts(ROWS))
    assert s['leaves'] == 4 and s['contra'] == 2   # 11202 + 12301
```

Note for the implementer: `ROWS` yields **4 distinct groups** (`111`, `112N`, `123`, `651`), so fix the first assertion to `{'groups': 4, 'leaves': 4}` before running (the count follows from `assign_group`).

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_ric_coa_import.py -m integration --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ric_coa.import_coa'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/ric_coa/import_coa.py
"""Import the RIC legacy accounting COA into the CAS ric.db (via the app factory)."""
import argparse, sqlite3
from collections import Counter
from scripts.ric_coa.mapping import build_accounts, GROUPS

LEGACY_DEFAULT = r"C:\envs\ric-workspace\legacy ric\accounting\instance\data.db"


def read_legacy(db_path):
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT a.account_number, a.account_title, t.account_type "
            "FROM accounts a JOIN account_type t ON a.account_type_id = t.id "
            "ORDER BY a.account_number").fetchall()
    finally:
        con.close()
    return [(str(n), ti, t) for n, ti, t in rows]


def assert_importable(session):
    from app.accounts.models import Account
    existing = {c for (c,) in session.query(Account.code).all()}
    clash = existing & set(GROUPS.keys())          # any group header already present?
    if clash:
        raise RuntimeError(f'{len(clash)} target group codes already exist '
                           f'(rebuild = clear first): {sorted(clash)[:5]}')
    return None


def write_accounts(specs, session):
    from app.accounts.models import Account
    from app.audit.utils import log_audit
    code_to_id, n_groups, n_leaves = {}, 0, 0
    for s in [x for x in specs if x.is_group] + [x for x in specs if not x.is_group]:
        acct = Account(code=s.code, name=s.name, account_type=s.account_type,
                       classification=s.classification, normal_balance=s.normal_balance,
                       parent_id=(code_to_id[s.parent_code] if s.parent_code else None),
                       is_active=True)
        session.add(acct); session.flush()
        code_to_id[s.code] = acct.id
        log_audit(module='accounts', action='import', record_id=acct.id,
                  record_identifier=f'{s.code} {s.name}', new_values=s.as_dict())
        if s.is_group: n_groups += 1
        else:          n_leaves += 1
    return {'groups': n_groups, 'leaves': n_leaves}


def summarize(specs):
    leaves = [s for s in specs if not s.is_group]
    by_section = Counter((s.account_type, s.classification) for s in leaves)
    return {
        'groups': sum(1 for s in specs if s.is_group),
        'leaves': len(leaves),
        'contra': sum(1 for s in leaves if s.normal_balance == 'credit' and s.account_type == 'Asset'),
        'by_section': {f'{t}/{c}': n for (t, c), n in sorted(by_section.items())},
    }


def _assert_target_is_ric(app):
    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    if not uri.endswith('ric.db'):
        raise SystemExit(f'SAFETY: target is not ric.db -> {uri}')


def main():
    ap = argparse.ArgumentParser(description='Import RIC legacy COA into CAS ric.db')
    ap.add_argument('--commit', action='store_true', help='write (default: dry-run)')
    ap.add_argument('--legacy', default=LEGACY_DEFAULT)
    args = ap.parse_args()

    from flask_app import app
    from app import db
    from app.accounts.models import Account

    rows = read_legacy(args.legacy)
    specs = build_accounts(rows)
    with app.app_context():
        _assert_target_is_ric(app)
        print('TARGET :', app.config['SQLALCHEMY_DATABASE_URI'])
        print('SUMMARY:', summarize(specs))
        # per-run leaf-code clash guard
        leaf_codes = [s.code for s in specs if not s.is_group]
        clash = {c for (c,) in db.session.query(Account.code)
                 .filter(Account.code.in_(leaf_codes)).all()}
        if clash:
            raise SystemExit(f'{len(clash)} legacy codes already present -> refusing '
                             f'(rebuild = clear first): {sorted(clash)[:5]}')
        if not args.commit:
            print('DRY RUN - nothing written. Re-run with --commit.')
            return
        result = write_accounts(specs, db.session)
        db.session.commit()
        print('COMMITTED:', result, '- total accounts now:', Account.query.count())


if __name__ == '__main__':
    main()
```

Note for the implementer: `assert_importable(session)` guards **group** codes; the CLI additionally guards **leaf** codes against the built specs (shown in `main`). The integration test calls `assert_importable` after a write that created group `111` etc., so the raise fires. Keep both guards.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_ric_coa_import.py -m integration --no-cov -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add -f scripts/ric_coa/import_coa.py tests/integration/test_ric_coa_import.py
git commit -m "feat(ric-coa): importer (read legacy, write via app factory, CLI dry-run/commit)"
```

---

### Task 4: Execute the import against `ric.db` (operator step)

**Files:** none created. Runs the tool against real client data.

**Preconditions:** the dev server holding `ric.db` is stopped (avoid write contention); `ric.db` holds only the 25-account seed (0 journal entries — verified in the spec).

- [ ] **Step 1: Stop any server on port 5050**

PowerShell: `Stop-Process -Id (Get-NetTCPConnection -LocalPort 5050 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue`

- [ ] **Step 2: Dry-run and review the summary**

Run (from `projects/cas`):
```bash
PYTHONPATH='C:\envs\erp-workspace\projects\cas' SQLALCHEMY_DATABASE_URI='sqlite:///ric.db' \
  venv/Scripts/python.exe -m scripts.ric_coa.import_coa --legacy "C:\envs\ric-workspace\legacy ric\accounting\instance\data.db"
```
Expected: `TARGET: sqlite:///ric.db`; `SUMMARY` shows `groups: 28, leaves: 338, contra: 13`; `DRY RUN - nothing written.` **Stop and confirm with the owner before Step 3.**

- [ ] **Step 3: Commit the import**

Re-run the same command with `--commit` appended.
Expected: `COMMITTED: {'groups': 28, 'leaves': 338} - total accounts now: 391`

- [ ] **Step 4: Verify acceptance criteria**

Run:
```bash
SQLALCHEMY_DATABASE_URI='sqlite:///ric.db' venv/Scripts/python.exe - <<'PY'
import os; os.environ['SQLALCHEMY_DATABASE_URI']='sqlite:///ric.db'
from flask_app import app
from app import db
from app.accounts.models import Account
with app.app_context():
    total = Account.query.count()
    has_children = {pid for (pid,) in db.session.query(Account.parent_id).filter(Account.parent_id.isnot(None)).distinct()}
    leaves = [a for a in Account.query.all() if a.parent_id is not None and a.id not in has_children]
    contra = Account.query.filter(Account.code.in_(['11202']+[f'123{i:02d}' for i in range(1,13)])).all()
    print('total accounts:', total, '(expect 391)')
    print('postable leaves:', len(leaves), '(expect >=338)')
    print('contra all credit:', all(a.normal_balance=='credit' for a in contra), '(expect True)')
    print('125/126 Current:', all(Account.query.filter_by(code=c).one().classification=='Current' for c in ['125','126']))
PY
```
Expected: total 391; leaves >= 338; contra all credit True; 125/126 Current True.

- [ ] **Step 5: Restart the dev server on `ric.db`**

PowerShell:
```powershell
$env:SQLALCHEMY_DATABASE_URI='sqlite:///ric.db'; $env:FLASK_PORT='5050'
Start-Process -NoNewWindow -FilePath 'C:\envs\erp-workspace\projects\cas\venv\Scripts\python.exe' -ArgumentList 'flask_app.py' -WorkingDirectory 'C:\envs\erp-workspace\projects\cas'
```
Then browse `/accounts` and confirm the RIC COA renders with proper-cased titles under the 28 group headers.

---

## Self-Review

**Spec coverage:** model reshape (Tasks 2–3), leaf field mapping + title casing (Tasks 1–2), TYPE_MAP + 28 groups + group codes incl. `112N` (Task 2), classification overrides `125`/`126` (Task 2), contra override 13 accounts leaves-only (Task 2), group-header fields incl. `normal_balance` (Task 2 `build_accounts` sets it from `DEFAULT_NORMAL_BALANCE`), audit per account (Task 3), keep-seed / no-clear (Task 3 has no clear path; idempotency guards), dry-run→commit + target safety (Task 3 `main`), acceptance criteria (Task 4). Non-goals (transactions, engine remap, seed retirement, revenue reclass) are correctly absent. ✔

**Placeholder scan:** no TBD/TODO; every code step shows complete code; the two implementer notes correct a deliberately-illustrative test assertion and clarify the two-layer guard — both give exact values. ✔

**Type consistency:** `AccountSpec` fields and `build_accounts`/`write_accounts`/`summarize` signatures match across Tasks 2–3; `assign_group` group codes match `GROUPS` keys (28) and the spec table. ✔
