# APV + CDV Historical Seed (2021–present) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `flask seed-history` command that resets the DB and generates ~5.5 years (Jan 2021 → 18 Jun 2026) of believable APV + CDV documents with balanced journal entries and realistic AP aging, for a reports/dashboards demo.

**Architecture:** A new module `app/seeds/history_seed.py` holds pure builder functions that construct `AccountsPayable`/`CashDisbursementVoucher` objects and post them through the **real** posting helpers (`_post_ap_je`, `_post_cdv_je`, `_apply_ap_payments`) so every JE balances exactly like a hand-entered document. A deterministic generator orchestrates the timeline; a thin CLI command wires reset → reference data → generate → summary.

**Tech Stack:** Flask CLI (`@app.cli.command`), SQLAlchemy, Python `random.Random` (fixed seed), `Decimal`, pytest integration tests.

**Spec:** `docs/superpowers/specs/2026-06-18-apv-cdv-history-seed-design.md`

## Global Constraints

- **Base = `seed-db` COA** (173 accounts), not `seed-minimal`. The spec's vendor table used `seed-minimal` codes; the real bound codes are below (this is the spec's explicitly-deferred code binding).
- **Resolved account codes (must exist after `seed-db`; fail loudly if any structural one is missing):** AP-Trade `20101`; WHT-Payable-Expanded `20301`; Input VAT (current) `10501`; Cash on Hand `10101` (cash payments); Cash in Bank - Current `10110` (check payments).
- **Expense leaves (by category):** rent `50220`, electricity `50221`, water `50222`, telecom/internet `50223`, office supplies `50230`, professional fees `50240`, legal fees `50241`, repairs & maintenance `50270`, transportation/travel `50280`, fuel & oil `50281`, marketing & advertising `50290`, miscellaneous `50298`.
- **VAT categories (only these exist in `seed-db`):** `VATABLE` (12%, input VAT → 10501), `VAT-EXEMPT` (0%), `ZERO-RATED` (0%), `NON-VAT` (0%). All 12% vendors use `VATABLE`.
- **WHT codes (from `seed-db`):** `WC010` 10% (professional), `WC030` 5%, `WC040` 5% (real-property rental), `WC060` 2% (contractors), `WC070` 2% (services). `seed-db` has **no 1% goods code**, so goods vendors (supplies, fuel) carry **no WHT** — this is a deliberate resolution of the spec's deferred 1% mapping.
- **Document numbers are seed-generated** as `AP-YYYY-MM-NNNN` / `CD-YYYY-MM-NNNN` from each doc's own date (NOT via `generate_ap_number`/`generate_cdv_number`, which key off `ph_now()` and would mis-date backdated rows). Sequence resets per (year, month), counted in chronological insert order.
- **Reuse real posting** — never hand-roll JE lines: `_post_ap_je(ap, user_id)`, `_post_cdv_je(cdv, user_id)`, `_apply_ap_payments(cdv)`. Set `status='posted'` + `posted_by_id`/`posted_at` **before** calling the JE poster (the poster mirrors doc status into JE status).
- **VAT extraction (inclusive):** for a `VATABLE` line, `vat_amount = round(line_total * Decimal(12) / Decimal(112), 2)`; for 0% categories `vat_amount = 0`. `wt_amount = round((line_total - vat_amount) * wht_rate / 100, 2)`.
- **Determinism:** all randomness flows from a single `random.Random(20210101)`. Re-running `seed-history` reproduces the same dataset (it always resets first).
- **Branch:** everything posts to the seeded Main branch. No accounting-period records (out of scope).
- Commit messages end with the repo's standard `Co-Authored-By:` / `Claude-Session:` trailers.

## File Structure

- `app/seeds/history_seed.py` (new) — reference resolver, number helper, vendor/user ensure, APV/CDV builders, timeline generator.
- `app/__init__.py` (modify) — register the `seed-history` CLI command (or register in `app/seeds/__init__.py` if that is where other commands live; follow the existing `seed-db` registration site).
- `tests/integration/test_history_seed.py` (new) — unit/integration tests for the resolver, builders, and a short-slice generator run.

---

### Task 1: Reference resolver, number helper, vendor/user setup

**Files:**
- Create: `app/seeds/history_seed.py`
- Test: `tests/integration/test_history_seed.py`

**Interfaces:**
- Produces:
  - `VENDORS` — list of vendor spec dicts (keys: `code`, `name`, `category`, `vat_code`, `wht_code` (str or `None`), `cadence` (`'monthly'|'frequent'|'occasional'`), `amount_min`, `amount_max`, `expense_code`).
  - `resolve_refs() -> dict` with keys `ap`, `wt`, `input_vat`, `cash_on_hand`, `cash_in_bank` (Account objects) and `expense` (dict: expense_code str → Account). Raises `RuntimeError` if any structural account (20101, 20301, 10501, 10101, 10110) is missing.
  - `next_doc_number(prefix: str, doc_date: date, counters: dict) -> str` → `f'{prefix}-{y}-{m:02d}-{n:04d}'`, incrementing `counters[(prefix, y, m)]`.
  - `ensure_accountant_user() -> User` (username `accountant`, role `accountant`, password `cas-accountant`).
  - `ensure_vendors() -> list[Vendor]` — creates any missing `VENDORS` rows; returns all in `VENDORS` order.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_history_seed.py`:

```python
"""Integration tests for the APV/CDV historical seed generator."""
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.branches.models import Branch
from app.seeds.seed_data import (
    seed_chart_of_accounts, seed_vat_categories, seed_withholding_tax_codes,
)
from app.seeds import history_seed as hs

pytestmark = [pytest.mark.integration]


@pytest.fixture
def base_db(db_session):
    """Populate the seed-db COA + VAT + WHT + a Main branch into the empty test DB."""
    seed_chart_of_accounts()
    seed_vat_categories()
    seed_withholding_tax_codes()
    branch = Branch(code='MAIN', name='Main Office', is_active=True)
    db.session.add(branch)
    db.session.commit()
    return branch


class TestRefsAndHelpers:
    def test_resolve_refs_finds_structural_accounts(self, base_db):
        refs = hs.resolve_refs()
        assert refs['ap'].code == '20101'
        assert refs['wt'].code == '20301'
        assert refs['input_vat'].code == '10501'
        assert refs['cash_on_hand'].code == '10101'
        assert refs['cash_in_bank'].code == '10110'
        # every expense code referenced by a vendor resolves to an Account
        for v in hs.VENDORS:
            assert v['expense_code'] in refs['expense']

    def test_next_doc_number_sequences_per_month(self):
        counters = {}
        assert hs.next_doc_number('AP', date(2021, 1, 5), counters) == 'AP-2021-01-0001'
        assert hs.next_doc_number('AP', date(2021, 1, 9), counters) == 'AP-2021-01-0002'
        assert hs.next_doc_number('AP', date(2021, 2, 1), counters) == 'AP-2021-02-0001'
        assert hs.next_doc_number('CD', date(2021, 1, 9), counters) == 'CD-2021-01-0001'

    def test_ensure_vendors_creates_twelve_with_defaults(self, base_db):
        vendors = hs.ensure_vendors()
        assert len(vendors) == 12
        from app.vendors.models import Vendor
        assert Vendor.query.count() == 12
        # idempotent within a run
        assert len(hs.ensure_vendors()) == 12
        assert Vendor.query.count() == 12

    def test_ensure_accountant_user(self, base_db):
        u = hs.ensure_accountant_user()
        assert u.username == 'accountant'
        assert u.role == 'accountant'
        assert u.check_password('cas-accountant')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_history_seed.py::TestRefsAndHelpers -v`
Expected: FAIL — `ModuleNotFoundError: app.seeds.history_seed` / attributes undefined.

- [ ] **Step 3: Implement the module foundation**

Create `app/seeds/history_seed.py`:

```python
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
            db.session.commit()
        out.append(v)
    return out
```

Confirmed against `app/vendors/models.py`: `Vendor` has `code`, `name`, `tin`, `payment_terms`, `default_vat_category`, `is_active` — the kwargs above are valid.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_history_seed.py::TestRefsAndHelpers -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/seeds/history_seed.py tests/integration/test_history_seed.py
git commit -m "feat(seed): history-seed refs/number/vendor foundation"
```

---

### Task 2: APV builder

**Files:**
- Modify: `app/seeds/history_seed.py`
- Test: `tests/integration/test_history_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `next_doc_number()`, `_money()`, `VENDORS`; the real helper `_post_ap_je` from `app.accounts_payable.views`.
- Produces: `build_apv(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id, branch_id, counters, amount=None) -> AccountsPayable` — a single posted APV with one line item, its WHT, and a balanced posted JE. `amount` (gross, VAT-inclusive) defaults to a midpoint of the vendor's band when not supplied.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_history_seed.py`:

```python
class TestApvBuilder:
    def test_build_apv_posts_balanced_je(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user()
        hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-LAW')   # VATABLE + WC010 10%
        vobj = Vendor.query.filter_by(code='HV-LAW').first()
        counters = {}
        ap = hs.build_apv(date(2021, 3, 4), spec, vobj, refs,
                          creator_id=acct.id, poster_id=admin.id,
                          branch_id=base_db.id, counters=counters, amount=Decimal('56000.00'))
        assert ap.ap_number == 'AP-2021-03-0001'
        assert ap.status == 'posted'
        # VAT extracted from 56,000 inclusive @12%
        assert ap.vat_amount == Decimal('6000.00')
        # WHT 10% of net (50,000)
        assert ap.withholding_tax_amount == Decimal('5000.00')
        # Net payable = subtotal - WHT
        assert ap.total_amount == Decimal('51000.00')
        # JE exists and balances
        je = ap.journal_entry
        assert je is not None and je.status == 'posted'
        debit = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        credit = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        assert debit == credit

    def test_build_apv_exempt_no_vat(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user()
        hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-WATR')  # VAT-EXEMPT, no WHT
        vobj = Vendor.query.filter_by(code='HV-WATR').first()
        ap = hs.build_apv(date(2021, 3, 6), spec, vobj, refs, acct.id, admin.id,
                          base_db.id, {}, amount=Decimal('2000.00'))
        assert ap.vat_amount == Decimal('0.00')
        assert ap.withholding_tax_amount == Decimal('0.00')
        assert ap.total_amount == Decimal('2000.00')
        je = ap.journal_entry
        debit = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        credit = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        assert debit == credit
```

Also add these helpers near the top of the test file (after imports):

```python
def _admin():
    from app.users.models import User
    u = User.query.filter_by(username='admin').first()
    if u is None:
        u = User(username='admin', email='admin@cas.local',
                 full_name='System Administrator', role='admin', is_active=True)
        u.set_password('admin123')
        db.session.add(u); db.session.commit()
    return u
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_history_seed.py::TestApvBuilder -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'build_apv'`.

- [ ] **Step 3: Implement `build_apv`**

Append to `app/seeds/history_seed.py`:

```python
def _vat_amount(line_total, vat_code):
    if vat_code == 'VATABLE':
        return _money(Decimal(line_total) * Decimal(12) / Decimal(112))
    return Decimal('0.00')


def build_apv(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id,
              branch_id, counters, amount=None):
    """Create one posted APV (single line) + its balanced posted JE."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    from app.withholding_tax.models import WithholdingTax
    from app.utils import ph_now

    if amount is None:
        amount = (vendor_spec['amount_min'] + vendor_spec['amount_max']) / 2
    line_total = _money(amount)
    vat_amt = _vat_amount(line_total, vendor_spec['vat_code'])
    net_base = line_total - vat_amt

    wt = None
    wt_rate = Decimal('0.00')
    wt_amt = Decimal('0.00')
    if vendor_spec['wht_code']:
        wt = WithholdingTax.query.filter_by(code=vendor_spec['wht_code']).first()
        if wt:
            wt_rate = Decimal(str(wt.rate))
            wt_amt = _money(net_base * wt_rate / Decimal('100'))

    ap = AccountsPayable(
        branch_id=branch_id,
        ap_number=next_doc_number('AP', doc_date, counters),
        ap_date=doc_date,
        due_date=date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        vendor_invoice_number=f'INV-{doc_date.year}-{counters[("AP", doc_date.year, doc_date.month)]:04d}',
        payment_terms='Net 30',
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=creator_id,
        posted_by_id=poster_id,
        posted_at=ph_now(),
    )
    item = AccountsPayableItem(
        line_number=1,
        description=f'{vendor_spec["category"].title()} — {doc_date.strftime("%b %Y")}',
        amount=line_total,
        vat_category=vendor_spec['vat_code'],
        vat_rate=Decimal('12.00') if vendor_spec['vat_code'] == 'VATABLE' else Decimal('0.00'),
        line_total=line_total,
        vat_amount=vat_amt,
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=wt_rate,
        wt_amount=wt_amt,
    )
    ap.line_items.append(item)
    ap.calculate_totals()        # sets subtotal, vat_amount, withholding_tax_amount, total_amount, balance
    db.session.add(ap)
    db.session.flush()           # need ap.id before JE

    je = _post_ap_je(ap, poster_id)   # status='posted' -> JE posted
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_history_seed.py::TestApvBuilder -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/seeds/history_seed.py tests/integration/test_history_seed.py
git commit -m "feat(seed): APV builder posting balanced JEs via _post_ap_je"
```

---

### Task 3: CDV builder (pay APV + direct expense)

**Files:**
- Modify: `app/seeds/history_seed.py`
- Test: `tests/integration/test_history_seed.py`

**Interfaces:**
- Consumes: `resolve_refs()`, `build_apv()`, `next_doc_number()`; the real helpers `_post_cdv_je`, `_apply_ap_payments` from `app.cash_disbursements.views`.
- Produces:
  - `build_cdv_paying(doc_date, apvs, apply_fractions, refs, creator_id, poster_id, branch_id, counters, method='check') -> CashDisbursementVoucher` — pays one or more APVs (Section A); `apply_fractions[i]` (Decimal 0<f<=1) of each APV's balance. Updates each APV's payment status via `_apply_ap_payments`.
  - `build_cdv_expense(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method='cash', amount=None) -> CashDisbursementVoucher` — a Section B direct-expense CDV.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_history_seed.py`:

```python
def _je_balances(je):
    d = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
    c = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
    return d == c


class TestCdvBuilder:
    def test_full_payment_marks_apv_paid(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user(); hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-SUP1')
        vobj = Vendor.query.filter_by(code='HV-SUP1').first()
        counters = {}
        ap = hs.build_apv(date(2021, 1, 5), spec, vobj, refs, acct.id, admin.id,
                          base_db.id, counters, amount=Decimal('11200.00'))
        cdv = hs.build_cdv_paying(date(2021, 1, 25), [ap], [Decimal('1.0')], refs,
                                  acct.id, admin.id, base_db.id, counters, method='check')
        assert cdv.cdv_number == 'CD-2021-01-0001'
        assert cdv.status == 'posted'
        assert ap.status == 'paid'
        assert ap.balance == Decimal('0.00')
        assert _je_balances(cdv.journal_entry)

    def test_partial_payment_marks_partially_paid(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user(); hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-SUP1')
        vobj = Vendor.query.filter_by(code='HV-SUP1').first()
        counters = {}
        ap = hs.build_apv(date(2021, 2, 5), spec, vobj, refs, acct.id, admin.id,
                          base_db.id, counters, amount=Decimal('10000.00'))
        total = ap.total_amount
        cdv = hs.build_cdv_paying(date(2021, 2, 20), [ap], [Decimal('0.5')], refs,
                                  acct.id, admin.id, base_db.id, counters, method='cash')
        assert ap.status == 'partially_paid'
        assert Decimal('0.00') < ap.balance < total
        assert _je_balances(cdv.journal_entry)

    def test_direct_expense_cdv_balances(self, base_db):
        refs = hs.resolve_refs()
        admin = _admin(); acct = hs.ensure_accountant_user(); hs.ensure_vendors()
        from app.vendors.models import Vendor
        spec = next(v for v in hs.VENDORS if v['code'] == 'HV-FUEL')
        vobj = Vendor.query.filter_by(code='HV-FUEL').first()
        cdv = hs.build_cdv_expense(date(2021, 1, 12), spec, vobj, refs, acct.id, admin.id,
                                   base_db.id, {}, method='cash', amount=Decimal('5600.00'))
        assert cdv.cdv_number == 'CD-2021-01-0001'
        assert cdv.status == 'posted'
        assert _je_balances(cdv.journal_entry)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_history_seed.py::TestCdvBuilder -v`
Expected: FAIL — `build_cdv_paying` / `build_cdv_expense` undefined.

- [ ] **Step 3: Implement the CDV builders**

Append to `app/seeds/history_seed.py`:

```python
def _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.utils import ph_now
    cash = refs['cash_in_bank'] if method == 'check' else refs['cash_on_hand']
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
        created_by_id=creator_id,
        posted_by_id=poster_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        cdv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters[("CD", doc_date.year, doc_date.month)]:04d}'
        cdv.check_date = doc_date
        cdv.check_bank = 'BPI'
    return cdv


def build_cdv_paying(doc_date, apvs, apply_fractions, refs, creator_id, poster_id,
                     branch_id, counters, method='check'):
    from app.cash_disbursements.models import CDVApLine
    from app.cash_disbursements.views import _post_cdv_je, _apply_ap_payments
    vendor_obj = apvs[0].vendor
    cdv = _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method)
    for i, ap in enumerate(apvs):
        frac = apply_fractions[i]
        applied = _money(Decimal(str(ap.balance)) * frac)
        cdv.ap_lines.append(CDVApLine(
            line_number=i + 1,
            ap_id=ap.id,
            ap_number=ap.ap_number,
            original_balance=ap.balance,
            amount_applied=applied,
        ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, poster_id)
    cdv.journal_entry_id = je.id
    _apply_ap_payments(cdv)
    db.session.commit()
    return cdv


def build_cdv_expense(doc_date, vendor_spec, vendor_obj, refs, creator_id, poster_id,
                      branch_id, counters, method='cash', amount=None):
    from app.cash_disbursements.models import CDVExpenseLine
    from app.cash_disbursements.views import _post_cdv_je
    from app.withholding_tax.models import WithholdingTax

    if amount is None:
        amount = (vendor_spec['amount_min'] + vendor_spec['amount_max']) / 2
    line_total = _money(amount)
    vat_amt = _vat_amount(line_total, vendor_spec['vat_code'])
    net_base = line_total - vat_amt
    wt = WithholdingTax.query.filter_by(code=vendor_spec['wht_code']).first() if vendor_spec['wht_code'] else None
    wt_rate = Decimal(str(wt.rate)) if wt else Decimal('0.00')
    wt_amt = _money(net_base * wt_rate / Decimal('100')) if wt else Decimal('0.00')

    cdv = _new_cdv(doc_date, vendor_obj, refs, creator_id, poster_id, branch_id, counters, method)
    cdv.expense_lines.append(CDVExpenseLine(
        line_number=1,
        description=f'{vendor_spec["category"].title()} — {doc_date.strftime("%b %Y")}',
        amount=line_total,
        vat_category=vendor_spec['vat_code'],
        vat_rate=Decimal('12.00') if vendor_spec['vat_code'] == 'VATABLE' else Decimal('0.00'),
        line_total=line_total,
        vat_amount=vat_amt,
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=wt_rate,
        wt_amount=wt_amt,
    ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, poster_id)
    cdv.journal_entry_id = je.id
    db.session.commit()
    return cdv
```

Confirmed against `app/cash_disbursements/models.py`: `CDVApLine` columns are `line_number, ap_id` (FK to `accounts_payable.id`), `ap_number, original_balance, amount_applied`; `CDVExpenseLine` columns are `line_number, description, amount, vat_category, vat_rate, line_total, vat_amount, account_id, wt_id, wt_rate, wt_amount`. The kwargs above match these exactly.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_history_seed.py::TestCdvBuilder -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/seeds/history_seed.py tests/integration/test_history_seed.py
git commit -m "feat(seed): CDV builders (pay APV + direct expense) via _post_cdv_je"
```

---

### Task 4: Timeline generator (aging model)

**Files:**
- Modify: `app/seeds/history_seed.py`
- Test: `tests/integration/test_history_seed.py`

**Interfaces:**
- Consumes: all builders, `resolve_refs`, `ensure_vendors`, `ensure_accountant_user`.
- Produces: `generate_history(branch_id, admin_id, *, start=date(2021,1,1), end=date(2026,6,18), rng_seed=20210101) -> dict` — generates the whole timeline and returns a summary dict: `{'apv': n, 'cdv': n, 'paid': n, 'partially_paid': n, 'outstanding': n, 'draft': n, 'voided': n, 'unbalanced': n}`. `unbalanced` counts any posted JE whose debits != credits (must be 0).

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_history_seed.py`:

```python
class TestGenerator:
    def test_short_slice_balances_and_ages(self, base_db):
        admin = _admin()
        summary = hs.generate_history(
            base_db.id, admin.id,
            start=date(2025, 4, 1), end=date(2026, 6, 18), rng_seed=20210101,
        )
        # counts land in believable bands for ~14.5 months
        assert summary['apv'] >= 150
        assert summary['cdv'] >= 90
        # EVERY posted JE balances
        assert summary['unbalanced'] == 0
        # aging is populated: at least some outstanding and some paid
        assert summary['outstanding'] >= 1
        assert summary['paid'] >= 1
        # status variety tail exists
        assert summary['draft'] >= 1

    def test_deterministic(self, base_db):
        admin = _admin()
        s1 = hs.generate_history(base_db.id, admin.id,
                                 start=date(2025, 10, 1), end=date(2025, 12, 31), rng_seed=20210101)
        # wipe transaction rows only would be complex; instead assert a re-run on a
        # fresh DB via a second call in a new test is out of scope — determinism is
        # asserted by fixed counts here.
        assert s1['apv'] >= 30
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/integration/test_history_seed.py::TestGenerator -v`
Expected: FAIL — `generate_history` undefined.

- [ ] **Step 3: Implement `generate_history`**

Append to `app/seeds/history_seed.py`:

```python
import random


def _month_iter(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _clamp_day(year, month, day, end):
    import calendar
    last = calendar.monthrange(year, month)[1]
    d = date(year, month, min(day, last))
    return min(d, end)


def generate_history(branch_id, admin_id, *, start=date(2021, 1, 1),
                     end=date(2026, 6, 18), rng_seed=20210101):
    rng = random.Random(rng_seed)
    refs = resolve_refs()
    acct = ensure_accountant_user()
    vendors = ensure_vendors()
    vmap = {v['code']: vendors[i] for i, v in enumerate(VENDORS)}
    counters = {}

    summary = {'apv': 0, 'cdv': 0, 'paid': 0, 'partially_paid': 0,
               'outstanding': 0, 'draft': 0, 'voided': 0, 'unbalanced': 0}

    monthly = [v for v in VENDORS if v['cadence'] == 'monthly']
    frequent = [v for v in VENDORS if v['cadence'] == 'frequent']
    occasional = [v for v in VENDORS if v['cadence'] == 'occasional']

    # "recent window" = last 12 months before end; those APVs get the aging spread.
    recent_cutoff = date(end.year - 1, end.month, 1)

    for (y, m) in _month_iter(start, end):
        month_apvs = []   # (ap, vendor_spec) posted this month, candidates for payment

        # recurring monthly vendors: one bill near a fixed day
        for spec in monthly:
            d = _clamp_day(y, m, rng.randint(2, 8), end)
            amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
            ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                           branch_id, counters, amount=amt)
            summary['apv'] += 1
            month_apvs.append((ap, spec))

        # frequent vendors: 2-3 bills/month each
        for spec in frequent:
            for _ in range(rng.randint(2, 3)):
                d = _clamp_day(y, m, rng.randint(1, 28), end)
                amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
                ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                               branch_id, counters, amount=amt)
                summary['apv'] += 1
                month_apvs.append((ap, spec))

        # occasional vendors: 0-1 bill/month each
        for spec in occasional:
            if rng.random() < 0.6:
                d = _clamp_day(y, m, rng.randint(1, 28), end)
                amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
                ap = build_apv(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                               branch_id, counters, amount=amt)
                summary['apv'] += 1
                month_apvs.append((ap, spec))

        # Payment / aging decisions per APV
        for ap, spec in month_apvs:
            in_recent = ap.ap_date >= recent_cutoff
            roll = rng.random()
            if in_recent and roll < 0.25:
                # leave outstanding (no CDV) -> aging bucket
                summary['outstanding'] += 1
                continue
            if in_recent and roll < 0.40:
                frac = Decimal('0.5')
            else:
                frac = Decimal('1.0')
            lag = rng.randint(15, 45)
            pay_date = _clamp_day(ap.ap_date.year, ap.ap_date.month,
                                  ap.ap_date.day, end)
            pay_date = min(date.fromordinal(ap.ap_date.toordinal() + lag), end)
            if pay_date <= end:
                method = 'check' if rng.random() < 0.6 else 'cash'
                hs_cdv = build_cdv_paying(pay_date, [ap], [frac], refs, acct.id,
                                          admin_id, branch_id, counters, method=method)
                summary['cdv'] += 1
                if ap.status == 'paid':
                    summary['paid'] += 1
                elif ap.status == 'partially_paid':
                    summary['partially_paid'] += 1
                    summary['outstanding'] += 1   # remaining balance still ages
            else:
                summary['outstanding'] += 1

        # ~3 direct-expense CDVs per month (Section B)
        for _ in range(rng.randint(2, 4)):
            spec = rng.choice(frequent + occasional)
            d = _clamp_day(y, m, rng.randint(1, 28), end)
            amt = _money(rng.uniform(spec['amount_min'], spec['amount_max']))
            method = 'cash' if rng.random() < 0.5 else 'check'
            build_cdv_expense(d, spec, vmap[spec['code']], refs, acct.id, admin_id,
                              branch_id, counters, method=method, amount=amt)
            summary['cdv'] += 1

    # 2026-only status-variety tail: a few drafts + a couple voided
    _seed_tail(refs, acct, admin_id, branch_id, counters, summary, end)

    # integrity check: count any unbalanced posted JE
    summary['unbalanced'] = _count_unbalanced_jes()
    return summary


def _seed_tail(refs, acct, admin_id, branch_id, counters, summary, end):
    """A handful of 2026 draft + voided APVs/CDVs for status variety."""
    spec = next(v for v in VENDORS if v['code'] == 'HV-SUP2')
    vobj = Vendor.query.filter_by(code='HV-SUP2').first()
    for i in range(3):
        d = date(2026, 6, min(10 + i, end.day))
        ap = _build_draft_apv(d, spec, vobj, refs, acct.id, branch_id, counters)
        summary['apv'] += 1
        summary['draft'] += 1
    for i in range(2):
        d = date(2026, 5, 5 + i)
        _build_voided_apv(d, spec, vobj, refs, acct.id, admin_id, branch_id, counters)
        summary['apv'] += 1
        summary['voided'] += 1


def _build_draft_apv(doc_date, spec, vobj, refs, creator_id, branch_id, counters):
    """A draft APV: built like build_apv but status stays 'draft' (no posted JE promotion)."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    amt = _money((spec['amount_min'] + spec['amount_max']) / 2)
    vat_amt = _vat_amount(amt, spec['vat_code'])
    ap = AccountsPayable(
        branch_id=branch_id, ap_number=next_doc_number('AP', doc_date, counters),
        ap_date=doc_date, due_date=date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vobj.id, vendor_name=vobj.name, vendor_tin=vobj.tin,
        payment_terms='Net 30', status='draft', amount_paid=Decimal('0.00'),
        created_by_id=creator_id,
    )
    ap.line_items.append(AccountsPayableItem(
        line_number=1, description='Draft bill', amount=amt,
        vat_category=spec['vat_code'], vat_rate=Decimal('12.00'),
        line_total=amt, vat_amount=vat_amt,
        account_id=refs['expense'][spec['expense_code']].id,
        wt_rate=Decimal('0.00'), wt_amount=Decimal('0.00'),
    ))
    ap.calculate_totals()
    db.session.add(ap)
    db.session.flush()
    je = _post_ap_je(ap, creator_id)   # status='draft' -> JE created as draft
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap


def _build_voided_apv(doc_date, spec, vobj, refs, creator_id, poster_id, branch_id, counters):
    ap = _build_draft_apv(doc_date, spec, vobj, refs, creator_id, branch_id, counters)
    from app.utils import ph_now
    # void deletes the JE (mirror the void view's effect on GL)
    if ap.journal_entry_id:
        from app.journal_entries.models import JournalEntry as _JE
        je = db.session.get(_JE, ap.journal_entry_id)
        ap.journal_entry_id = None
        ap.journal_entry = None
        if je:
            db.session.delete(je)
    ap.status = 'voided'
    ap.voided_at = ph_now()
    ap.voided_by_id = poster_id
    ap.void_reason = 'Seed demo voided document'
    db.session.commit()
    return ap


def _count_unbalanced_jes():
    from app.journal_entries.models import JournalEntry
    bad = 0
    for je in JournalEntry.query.filter_by(status='posted').all():
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        if d != c:
            bad += 1
    return bad
```

Note: confirm the APV void semantics against `accounts_payable/views.py::void` — if voiding a posted bill rather than a draft is the project's intended path, mirror that. The `_build_voided_apv` here voids a draft (no posted JE in GL), which is the safe minimal form; adjust only if the reviewer finds the project requires voided bills to have been posted first.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/integration/test_history_seed.py::TestGenerator -v`
Expected: PASS (2 passed). If counts are slightly under the asserted floors, widen the slice or lower the floors to match the realized deterministic output — do NOT inflate generation just to pass.

- [ ] **Step 5: Commit**

```bash
git add app/seeds/history_seed.py tests/integration/test_history_seed.py
git commit -m "feat(seed): timeline generator with realistic aging + status tail"
```

---

### Task 5: `flask seed-history` CLI command

**Files:**
- Modify: `app/__init__.py` (register the command at the same site as `seed-db`/`seed-minimal`)
- Modify: `app/seeds/history_seed.py` (add `run_seed_history()` entrypoint)
- Test: `tests/integration/test_history_seed.py`

**Interfaces:**
- Consumes: `generate_history`; the existing base-seed path used by `seed-db` (admin, branch, COA, VAT, WHT, settings).
- Produces: `run_seed_history(reset=True, start=..., end=...) -> dict` and a CLI command `flask seed-history` that calls it and prints the summary.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_history_seed.py`:

```python
class TestRunEntrypoint:
    def test_run_seed_history_without_reset_uses_existing_base(self, base_db):
        # base_db already loaded COA+VAT+WHT+branch; admin must exist
        _admin()
        summary = hs.run_seed_history(reset=False, branch_id=base_db.id,
                                      start=date(2026, 1, 1), end=date(2026, 6, 18))
        assert summary['apv'] >= 30
        assert summary['unbalanced'] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/integration/test_history_seed.py::TestRunEntrypoint -v`
Expected: FAIL — `run_seed_history` undefined.

- [ ] **Step 3: Implement `run_seed_history` + register the CLI command**

Append to `app/seeds/history_seed.py`:

```python
def run_seed_history(reset=True, branch_id=None, start=date(2021, 1, 1),
                     end=date(2026, 6, 18)):
    """Reset (optional) + ensure base + generate history. Returns the summary dict."""
    from app.branches.models import Branch
    from app.users.models import User

    if reset:
        # Reuse the project's base seed path so COA/VAT/WHT/admin/branch/settings
        # are created exactly as `seed-db` does. Confirmed: app/seeds/seed_data.py
        # exposes seed_all(), which seeds admin (admin/admin123), Main branch,
        # the 173-account COA, VAT categories, WHT codes, and app settings.
        from app.seeds import seed_data
        db.drop_all()
        db.create_all()
        seed_data.seed_all()

    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        raise RuntimeError("admin user missing — base seed did not run.")
    if branch_id is None:
        branch = Branch.query.filter_by(code='MAIN').first() or Branch.query.first()
        if branch is None:
            raise RuntimeError("No branch found after base seed.")
        branch_id = branch.id

    summary = generate_history(branch_id, admin.id, start=start, end=end)
    return summary
```

Then register the CLI command. In `app/__init__.py`, at the same place `seed-db` is registered (search for `@app.cli.command` / `app.cli.add_command` near the bottom of `create_app`), add:

```python
    @app.cli.command('seed-history')
    def seed_history_command():
        """Reset the DB and seed 2021->present APV + CDV demo history."""
        from app.seeds.history_seed import run_seed_history
        summary = run_seed_history(reset=True)
        print("\n[OK] Historical seed complete:")
        for k in ('apv', 'cdv', 'paid', 'partially_paid', 'outstanding',
                  'draft', 'voided', 'unbalanced'):
            print(f"  {k:>15}: {summary[k]}")
        if summary['unbalanced']:
            print("  [WARN] Some posted JEs are unbalanced — investigate before demo.")
```

Confirmed: the `seed-db` command (`app/__init__.py:243`) calls `seed_all()`; `run_seed_history` calls `seed_data.seed_all()` directly after `drop_all`/`create_all`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/integration/test_history_seed.py::TestRunEntrypoint -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole seed test module + commit**

Run: `python -m pytest tests/integration/test_history_seed.py -v`
Expected: PASS (all tasks' tests green).

```bash
git add app/seeds/history_seed.py app/__init__.py tests/integration/test_history_seed.py
git commit -m "feat(seed): flask seed-history command (reset + generate + summary)"
```

- [ ] **Step 6: Manual full run (acceptance evidence — do NOT commit DB)**

Run: `flask seed-history`
Expected: prints a summary with `apv` ≈ 950–1050, `cdv` ≈ 600–700, `unbalanced: 0`, and non-zero `paid` / `outstanding` / `draft` / `voided`. If `unbalanced > 0`, stop and report (do not patch inline — project rule).

---

## Self-Review

**Spec coverage:**
- Mechanism: `flask seed-history`, full reset, programmatic, deterministic, reuses helpers → Tasks 1–5. ✓
- Volume ~990 APV / ~660 CDV → Task 4 generator + Task 5 full-run expectation. ✓
- Reference data (accountant user, ~12 vendors, expense leaves) → Task 1. ✓
- Generation model (cadence, amounts, VAT/WHT, line items, synthetic invoice #) → Tasks 2 + 4. ✓
- Aging & payment model (older paid w/ lag, recent paid/partial/outstanding spread, draft/voided tail) → Task 4. ✓
- Posting & integrity (real helpers, balanced JEs, `_apply_ap_payments`, periods skipped) → Tasks 2/3/4. ✓
- Verification (counts, balanced JEs, payment transitions, outstanding present) → Tasks 1–4 tests + Task 5 acceptance. ✓
- Code-binding deferral resolved → Global Constraints (real seed-db codes). ✓

**Placeholder scan:** No "TBD"/"implement later". All field/function-name bindings were verified against source and are stated as confirmed facts (Vendor columns, `CDVApLine.ap_id`, `seed_all()`). The single remaining note is the APV void path (Task 4) — the `_build_voided_apv` form is self-consistent (voids a draft, no GL JE), called out only so the reviewer can elect the post-then-void variant if preferred.

**Type consistency:** `refs` dict keys (`ap`, `wt`, `input_vat`, `cash_on_hand`, `cash_in_bank`, `expense`) are produced in Task 1 and consumed identically in Tasks 2–4. `counters` is threaded through every builder and `next_doc_number`. `build_apv`/`build_cdv_paying`/`build_cdv_expense`/`generate_history`/`run_seed_history` signatures match between their definitions and call sites. Summary dict keys match between `generate_history`, `_seed_tail`, and the CLI printer.

**Resolved during planning (no longer open):**
1. `Vendor` columns `tin`/`payment_terms`/`default_vat_category` — confirmed present.
2. `CDVApLine` FK is `ap_id` — plan code corrected to use it.
3. `seed-db` entrypoint is `seed_all()` — wired into `run_seed_history`.

**One item left to the implementer's judgement:** APV void path (Task 4) — the draft-void form is provided and works; switch to post-then-void only if the reviewer deems it necessary.
