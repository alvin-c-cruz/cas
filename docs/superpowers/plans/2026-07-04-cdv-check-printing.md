# CDV Check Printing + Per-Account Editable Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a check-paid CDV print a data overlay onto physical pre-printed check stock, using an editable layout that is per cash/bank account (a Default layout plus per-account overrides), reusing the existing P-69 pre-printed-forms engine.

**Architecture:** Add a `CD_CHECK` layout slot and a nullable `account_id` dimension to the existing `PrintLayout` model (Option A — no `variant` column). A check layout resolves by the CDV's `cash_account_id` with fallback to the Default (`account_id IS NULL`). A new `print_check` route on the CDV renders the overlay; a new `cd_check_print_access` setting gates posted-vs-draft; the existing 5 voucher overlays are untouched because `account_id` defaults to `NULL`.

**Tech Stack:** Flask, SQLAlchemy, Flask-Migrate/Alembic, SQLite, fpdf2, pytest. Source spec: `docs/superpowers/specs/2026-07-04-cdv-check-printing-design.md`.

## Global Constraints

- **Run from `projects/cas/`** with the project venv: `C:/envs/erp-workspace/projects/cas/venv/Scripts/python -m pytest ...` (or `python` if it resolves to the venv). Dev server on port 5050.
- **TDD mandatory** — write the failing test first, watch it fail, then implement (CLAUDE.md).
- **Model-change already approved** by the user (2026-07-04): `PrintLayout.account_id` + composite unique + `String(16)` + `save()` persists page dims. No further model changes without new approval.
- **Verify audit in CRUD/action tests** — after a write/action that should audit, assert a `log_audit` row exists (CLAUDE.md).
- **No JS popups** — no `confirm()`/`alert()`/`prompt()`; custom HTML modals with `{{ csrf_token() }}` only.
- **Peso sign:** never printed on the check (fpdf core font is latin-1; `_fmt_money` emits bare numbers by design). In templates use the literal `₱` (U+20B1), never `&#8369;`.
- **Jinja `{# #}` comments** (never `<!-- -->`) near role/condition-gated markup, or the text leaks into `resp.data` and breaks absence tests.
- **Amount source** for the check face value = `CashDisbursementVoucher.total_amount` (= AP applied + expense − WHT = net cash disbursed). Never a pre-WHT figure.
- **`active` is type-level** for CD_CHECK: it lives on the **Default** row (`account_id IS NULL`) and is the master on/off for check printing; per-account rows override background/fields/page-dims only (see Task 5 resolution).
- **Static assets:** if any `app/static/*` file changes, bump its `?v=N` cache-buster on every template link in the same commit (none expected in this plan).
- **Commit after each task.** Work on `main` (no branch). Do not push (user pushes explicitly).

---

## File Structure

- `app/preprinted_forms/models.py` — `PrintLayout` gains `account_id`, composite unique, wider `voucher_type`; `VOUCHER_TYPES`/`VOUCHER_LABELS` gain `CD_CHECK`.
- `migrations/versions/<rev>_printlayout_account_id.py` — the schema migration.
- `app/preprinted_forms/field_catalog.py` — `amount_in_words` overflow/rounding fix; `FIELD_CATALOG['CD_CHECK']`.
- `app/preprinted_forms/pdf.py` — `can_print` `CD_CHECK` arm; `resolve_check_layout()` helper.
- `app/preprinted_forms/views.py` — `_TEST_PRINT_MODEL_NAMES['CD_CHECK']`; designer/save/upload/toggle accept optional `account_id`; `save()` persists page dims; admin list shows Default rows only.
- `app/preprinted_forms/templates/preprinted_forms/designer.html` + `admin_toggles.html` — account selector on the check designer.
- `app/settings.py` (+ seed) — register/seed `cd_check_print_access`.
- `app/cash_disbursements/views.py` — `print_check` route; `check_layout_ready` in `view()`.
- `app/cash_disbursements/templates/cash_disbursements/detail.html` — gated "Print Check" button.
- `projects/cas/.claude/regression-map.json` — add `app/preprinted_forms/pdf.py` + `field_catalog.py`.
- Tests under `tests/unit/` and `tests/integration/`.

---

### Task 1: `amount_in_words` money-correctness fix

Fix the release-blocking overflow (blank legal line ≥ 1 trillion) and align rounding to HALF_UP. Pure-function change; no dependency on the rest.

**Files:**
- Modify: `app/preprinted_forms/field_catalog.py` (`_SCALES` ~line 77; `amount_in_words` ~line 116-133)
- Test: `tests/unit/test_field_catalog.py`

**Interfaces:**
- Produces: `amount_in_words(value) -> str` — unchanged signature; now never raises / never returns `''` for a finite in-range amount; uses `ROUND_HALF_UP`.

- [ ] **Step 1: Write the failing boundary tests**

```python
# tests/unit/test_field_catalog.py  (add)
import pytest
from decimal import Decimal
from app.preprinted_forms.field_catalog import amount_in_words

@pytest.mark.parametrize("value,expected", [
    (Decimal("1.00"),    "One Peso and 00/100"),
    (Decimal("2.00"),    "Two Pesos and 00/100"),
    (Decimal("0.00"),    "Zero Pesos and 00/100"),
    (Decimal("0.05"),    "Zero Pesos and 05/100"),
    (Decimal("0.99"),    "Zero Pesos and 99/100"),
    (Decimal("100.00"),  "One Hundred Pesos and 00/100"),
    (Decimal("1000.00"), "One Thousand Pesos and 00/100"),
    (Decimal("1001.00"), "One Thousand One Pesos and 00/100"),
    (Decimal("1234.50"), "One Thousand Two Hundred Thirty-Four Pesos and 50/100"),
    (Decimal("1000000.00"),     "One Million Pesos and 00/100"),
    (Decimal("1000000000.00"),  "One Billion Pesos and 00/100"),
    (Decimal("21.00"),   "Twenty-One Pesos and 00/100"),
    (Decimal("999999999999.99"), "Nine Hundred Ninety-Nine Billion Nine Hundred Ninety-Nine "
                                 "Million Nine Hundred Ninety-Nine Thousand Nine Hundred "
                                 "Ninety-Nine Pesos and 99/100"),
])
def test_amount_in_words_boundaries(value, expected):
    assert amount_in_words(value) == expected

def test_amount_in_words_trillion_not_blank():
    # Was: IndexError swallowed -> blank legal line on the check.
    out = amount_in_words(Decimal("1000000000000.00"))
    assert out.startswith("One Trillion")
    assert out.endswith("00/100")

def test_amount_in_words_half_up():
    # A 3dp input rounds half-up at the centavo (defensive; column is 2dp today).
    assert amount_in_words(Decimal("0.005")) == "Zero Pesos and 01/100"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_field_catalog.py -k amount_in_words -v`
Expected: FAIL — `test_amount_in_words_trillion_not_blank` errors/blank; `half_up` gives `00/100` (banker's rounding).

- [ ] **Step 3: Implement the fix**

```python
# app/preprinted_forms/field_catalog.py
# Extend scales so no realistic peso amount overflows into a swallowed IndexError.
_SCALES = ('', 'Thousand', 'Million', 'Billion', 'Trillion', 'Quadrillion')

# in amount_in_words(...), change the quantize line from ROUND_HALF_EVEN (default) to HALF_UP:
    amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

Add the import at the top of the file:

```python
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
```

(Guard note: `_int_to_words` still indexes `_SCALES[scale_idx]`; with 6 scales it supports up to 999 quadrillion − 1, far beyond any `Numeric(15,2)` value — `total_amount` maxes at 9,999,999,999,999.99, i.e. Trillions. No blank possible in range.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/unit/test_field_catalog.py -k amount_in_words -v`
Expected: PASS (all boundary + trillion + half_up).

- [ ] **Step 5: Commit**

```bash
git add app/preprinted_forms/field_catalog.py tests/unit/test_field_catalog.py
git commit -m "fix(preprinted): amount_in_words no longer blanks >=1T; round HALF_UP"
```

---

### Task 2: `PrintLayout` model change + migration

Add the per-account dimension. `account_id` defaults to `NULL`, so the 5 existing overlays are unchanged.

**Files:**
- Modify: `app/preprinted_forms/models.py` (class `PrintLayout` ~line 17-29)
- Create: `migrations/versions/<rev>_printlayout_account_id.py` (via `flask db migrate`, then edited)
- Test: `tests/unit/test_preprinted_model.py`

**Interfaces:**
- Produces: `PrintLayout.account_id` (nullable int FK → `accounts.id`); composite unique `(voucher_type, account_id)`; `voucher_type` is `String(16)`. Existing `get_fields/set_fields/get_line_band/set_line_band` unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_preprinted_model.py  (add; keep existing tests)
from app import db
from app.preprinted_forms.models import PrintLayout

def test_printlayout_account_id_and_composite_unique(db_session):
    default = PrintLayout(voucher_type='CD_CHECK', account_id=None)
    acct = PrintLayout(voucher_type='CD_CHECK', account_id=1)
    db.session.add_all([default, acct])
    db.session.commit()
    # Same voucher_type with different account_id is allowed (composite unique).
    assert PrintLayout.query.filter_by(voucher_type='CD_CHECK').count() == 2
    assert default.account_id is None and acct.account_id == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_preprinted_model.py::test_printlayout_account_id_and_composite_unique -v`
Expected: FAIL — `TypeError`/`AttributeError` (`account_id` unknown).

- [ ] **Step 3: Edit the model**

```python
# app/preprinted_forms/models.py
class PrintLayout(db.Model):
    __tablename__ = 'print_layouts'
    __table_args__ = (
        db.UniqueConstraint('voucher_type', 'account_id',
                            name='uq_print_layouts_voucher_type_account_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    voucher_type = db.Column(db.String(16), nullable=False, index=True)  # SI/CR/CD/AP/JV/CD_CHECK
    # NULL = the Default layout for this slot; a value = that cash/bank account's override.
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True, index=True)
    active = db.Column(db.Boolean, default=False, nullable=False)
    background_image = db.Column(db.String(200), nullable=True)
    page_width_mm = db.Column(db.Numeric(6, 2), default=215.90, nullable=False)
    page_height_mm = db.Column(db.Numeric(6, 2), default=279.40, nullable=False)
    fields_json = db.Column(db.Text, default='[]')
    line_band_json = db.Column(db.Text, default='{}')
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by = db.Column(db.String(80))
    # ... get_fields/set_fields/get_line_band/set_line_band unchanged ...
```

(Removed `unique=True` from `voucher_type`; the composite `UniqueConstraint` replaces it.)

- [ ] **Step 4: Generate + edit the migration**

Run: `python -m flask db migrate -m "printlayout account_id + composite unique + wider voucher_type"`

Then open the new file under `migrations/versions/` and ensure `upgrade()` uses **batch mode** (SQLite cannot alter constraints in place). It should read like:

```python
def upgrade():
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
        batch_op.alter_column('voucher_type',
                              existing_type=sa.String(length=8), type_=sa.String(length=16),
                              existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_print_layouts_account_id'), ['account_id'], unique=False)
        batch_op.create_foreign_key('fk_print_layouts_account_id_accounts',
                                    'accounts', ['account_id'], ['id'])
        batch_op.create_unique_constraint('uq_print_layouts_voucher_type_account_id',
                                          ['voucher_type', 'account_id'])
        # The old single-column unique on voucher_type is dropped by table recreation
        # (batch mode rebuilds the table from the model's current constraints).

def downgrade():
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.drop_constraint('uq_print_layouts_voucher_type_account_id', type_='unique')
        batch_op.drop_constraint('fk_print_layouts_account_id_accounts', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_print_layouts_account_id'))
        batch_op.alter_column('voucher_type', existing_type=sa.String(length=16),
                              type_=sa.String(length=8), existing_nullable=False)
        batch_op.drop_column('account_id')
```

- [ ] **Step 5: Apply the migration**

Run: `python -m flask db upgrade`
Expected: no traceback; on a fresh SQLite it prints only the SQLiteImpl/non-transactional DDL notice.

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_preprinted_model.py -v`
Expected: PASS (new test + existing model tests — note the exact-tuple test is updated in Task 3, so it may still show the 5-tuple here; that is fine until Task 3).

- [ ] **Step 7: Commit**

```bash
git add app/preprinted_forms/models.py migrations/versions/ tests/unit/test_preprinted_model.py
git commit -m "feat(preprinted): PrintLayout per-account layouts (account_id + composite unique)"
```

---

### Task 3: Register `CD_CHECK` type + field catalog (+ stale-test fixes)

**Files:**
- Modify: `app/preprinted_forms/models.py` (`VOUCHER_TYPES`, `VOUCHER_LABELS` ~line 6-14)
- Modify: `app/preprinted_forms/field_catalog.py` (`FIELD_CATALOG` ~line 223)
- Modify: `app/preprinted_forms/views.py` (`_TEST_PRINT_MODEL_NAMES` ~line 42-48)
- Test: `tests/unit/test_field_catalog.py`, `tests/unit/test_preprinted_model.py`, `tests/integration/test_preprinted_forms.py`

**Interfaces:**
- Produces: `VOUCHER_TYPES` includes `'CD_CHECK'`; `FIELD_CATALOG['CD_CHECK']` has keys `header` (check_date, payee, total, amount_in_words, check_number, memo) and `line_columns` (`[]`); `resolve_field('CD_CHECK', key, cdv)` works.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_field_catalog.py  (add)
from app.preprinted_forms.field_catalog import FIELD_CATALOG, resolve_field

def test_cd_check_catalog_shape():
    cat = FIELD_CATALOG['CD_CHECK']
    assert 'header' in cat and 'line_columns' in cat
    assert cat['line_columns'] == []
    keys = {f['key'] for f in cat['header']}
    assert {'check_date', 'payee', 'total', 'amount_in_words', 'check_number', 'memo'} <= keys

def test_cd_check_resolves_from_cdv():
    class FakeCDV:
        vendor_name = 'ACME BUILDERS'
        total_amount = 1234.50
        check_number = '00123'
    assert resolve_field('CD_CHECK', 'payee', FakeCDV()) == 'ACME BUILDERS'
    assert resolve_field('CD_CHECK', 'check_number', FakeCDV()) == '00123'
    assert resolve_field('CD_CHECK', 'amount_in_words', FakeCDV()).startswith('One Thousand Two Hundred')
```

Also update the stale exact-tuple assert (this is a justified stale-fail, not a loosened guard):

```python
# tests/unit/test_preprinted_model.py  — update the existing assertion
# BEFORE: assert VOUCHER_TYPES == ('SI', 'CR', 'CD', 'AP', 'JV')
assert VOUCHER_TYPES == ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_field_catalog.py -k cd_check tests/unit/test_preprinted_model.py -v`
Expected: FAIL — `KeyError: 'CD_CHECK'` / tuple mismatch.

- [ ] **Step 3: Register the type + catalog + test-print model**

```python
# app/preprinted_forms/models.py
VOUCHER_TYPES = ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK')  # 'CD_CHECK' = 8 chars (voucher_type is String(16))
VOUCHER_LABELS = {
    'SI': 'Sales Invoice',
    'CR': 'Cash Receipt Voucher',
    'CD': 'Cash Disbursement Voucher',
    'AP': 'Accounts Payable Voucher',
    'JV': 'Journal Voucher',
    'CD_CHECK': 'Cash Disbursement — Check',
}
```

```python
# app/preprinted_forms/field_catalog.py  — add to FIELD_CATALOG
    'CD_CHECK': {
        'header': [
            _hf('check_date', 'Check Date', _attr_date('check_date')),
            _hf('payee', 'Payee (Vendor)', _attr_str('vendor_name')),
            _hf('total', 'Amount (Figures)', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('check_number', 'Check Number', _attr_str('check_number')),
            _hf('memo', 'Memo', _attr_str('notes')),
        ],
        'line_columns': [],   # a check has no line band
    },
```

(No `_LINE_ATTR['CD_CHECK']` entry — `iter_lines` returns `[]`, `render_preprinted`'s band loop is a no-op.)

```python
# app/preprinted_forms/views.py  — add to _TEST_PRINT_MODEL_NAMES
    'CD_CHECK': ('app.cash_disbursements.models', 'CashDisbursementVoucher'),
```

- [ ] **Step 4: Close the coverage holes in the iterating tests**

In `tests/unit/test_field_catalog.py` and `tests/integration/test_preprinted_forms.py`, find the hardcoded `('SI','CR','CD','AP','JV')` loop literals and add `'CD_CHECK'` so those loops actually exercise the new type. (Grep: `('SI', 'CR', 'CD', 'AP', 'JV')` and `'SI', 'CR', 'CD', 'AP', 'JV'`.)

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py -v`
Expected: PASS. If an integration test asserts the admin toggle list shows exactly 5 rows, that is a stale-fail — update it in this commit to expect the Default rows for 6 types (Task 5 makes the admin list Default-only; until then it counts distinct types). Re-grep the failing assert for the changed surface before editing.

- [ ] **Step 6: Commit**

```bash
git add app/preprinted_forms/ tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): register CD_CHECK layout type + field catalog"
```

---

### Task 4: `cd_check_print_access` setting + `can_print` arm

**Files:**
- Modify: `app/settings.py` (the `SETTINGS_KEYS` list / defaults — grep `cd_print_access` to find the sibling)
- Modify: `app/seeds/seed_data.py` (seed the default alongside other `*_print_access` — grep `cd_print_access`)
- Modify: `app/preprinted_forms/pdf.py` (`can_print` ~line 16-43)
- Test: `tests/integration/test_preprinted_forms.py` (or `tests/unit/test_preprinted_pdf.py` if present)

**Interfaces:**
- Produces: setting key `cd_check_print_access` (default `'posted_only'`, values `posted_only`/`draft_and_posted`); `can_print('CD_CHECK', cdv)` honors it (posted → posted_only; not voided/cancelled → draft_and_posted).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_preprinted_forms.py  (add)
from app.preprinted_forms.pdf import can_print
from app.settings import AppSettings

def _mk_cdv(status):
    from app.cash_disbursements.models import CashDisbursementVoucher
    c = CashDisbursementVoucher(); c.status = status; return c

def test_can_print_cd_check_posted_only(db_session):
    AppSettings.set_setting('cd_check_print_access', 'posted_only')
    assert can_print('CD_CHECK', _mk_cdv('posted')) is True
    assert can_print('CD_CHECK', _mk_cdv('draft')) is False

def test_can_print_cd_check_draft_and_posted(db_session):
    AppSettings.set_setting('cd_check_print_access', 'draft_and_posted')
    assert can_print('CD_CHECK', _mk_cdv('draft')) is True
    assert can_print('CD_CHECK', _mk_cdv('voided')) is False
```

(If `AppSettings.set_setting` differs, match the setter used elsewhere in the suite — grep `set_setting`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k can_print_cd_check -v`
Expected: FAIL — `can_print('CD_CHECK', ...)` returns `False` (hits the `else` branch).

- [ ] **Step 3: Add the setting + the `can_print` arm**

Register `cd_check_print_access` in `app/settings.py` next to `cd_print_access` (same structure/default `'posted_only'`), and seed it in `seed_data.py` where the other `*_print_access` keys are seeded.

```python
# app/preprinted_forms/pdf.py  — inside can_print(), add BEFORE the final else
    elif voucher_type == 'CD_CHECK':
        setting = AppSettings.get_setting('cd_check_print_access', 'posted_only')
        posted_ok = record.status == 'posted'
```

(The `if setting == 'posted_only' ... draft_and_posted ...` tail already applies to the new arm.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k can_print_cd_check -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/settings.py app/seeds/seed_data.py app/preprinted_forms/pdf.py tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): cd_check_print_access setting + can_print CD_CHECK arm"
```

---

### Task 5: `resolve_check_layout()` — account → Default resolution

**Files:**
- Modify: `app/preprinted_forms/pdf.py` (add helper)
- Modify: `app/preprinted_forms/views.py` (`admin()` ~line 136-141 — show Default rows only)
- Test: `tests/integration/test_preprinted_forms.py`

**Interfaces:**
- Produces: `resolve_check_layout(cdv) -> PrintLayout | None`. Rule: the Default row (`CD_CHECK, account_id IS NULL`) is the master switch — if missing or `active is False`, return `None`. Otherwise choose the CDV's account override (`CD_CHECK, account_id == cdv.cash_account_id`) if it exists **and has a background_image**, else the Default; return it only if it has a `background_image`, else `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_preprinted_forms.py  (add)
from app.preprinted_forms.pdf import resolve_check_layout
from app.preprinted_forms.models import PrintLayout
from app import db

class _CDV:  # minimal stand-in
    def __init__(self, cash_account_id): self.cash_account_id = cash_account_id

def test_resolve_check_layout_default_and_override(db_session):
    default = PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True, background_image='d.png')
    override = PrintLayout(voucher_type='CD_CHECK', account_id=7, active=True, background_image='o.png')
    db.session.add_all([default, override]); db.session.commit()
    assert resolve_check_layout(_CDV(7)).background_image == 'o.png'   # account override wins
    assert resolve_check_layout(_CDV(99)).background_image == 'd.png'  # falls back to Default

def test_resolve_check_layout_master_off(db_session):
    PrintLayout.query.delete()
    db.session.add(PrintLayout(voucher_type='CD_CHECK', account_id=None, active=False, background_image='d.png'))
    db.session.commit()
    assert resolve_check_layout(_CDV(7)) is None   # Default inactive -> master off

def test_resolve_check_layout_no_background(db_session):
    PrintLayout.query.delete()
    db.session.add(PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True, background_image=None))
    db.session.commit()
    assert resolve_check_layout(_CDV(7)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k resolve_check_layout -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_check_layout'`.

- [ ] **Step 3: Implement the helper + fix the admin list**

```python
# app/preprinted_forms/pdf.py  (add)
def resolve_check_layout(cdv):
    """Resolve the CD_CHECK PrintLayout for a CDV, account override -> Default.
    The Default (account_id IS NULL) row's `active` is the master switch."""
    from app.preprinted_forms.models import PrintLayout
    default = PrintLayout.query.filter_by(voucher_type='CD_CHECK', account_id=None).first()
    if not default or not default.active:
        return None
    override = PrintLayout.query.filter_by(
        voucher_type='CD_CHECK', account_id=cdv.cash_account_id).first()
    chosen = override if (override and override.background_image) else default
    return chosen if chosen.background_image else None
```

```python
# app/preprinted_forms/views.py  — admin(): only Default rows drive the toggle list
    layouts = {l.voucher_type: l
               for l in PrintLayout.query.filter_by(account_id=None).all()}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k resolve_check_layout -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/preprinted_forms/pdf.py app/preprinted_forms/views.py tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): resolve_check_layout (account override -> Default); admin lists Default rows"
```

---

### Task 6: `print_check` route + audit

**Files:**
- Modify: `app/cash_disbursements/views.py` (near `print_cdv` ~line 1141)
- Test: `tests/integration/test_cash_disbursements.py` (or the CDV test module — grep `def test_print_cdv`)

**Interfaces:**
- Consumes: `resolve_check_layout` (Task 5), `can_print` (Task 4), `render_preprinted`, `_get_cdv_or_404`, `log_audit`.
- Produces: route `cash_disbursements.print_check` at `/cash-disbursements/<int:id>/print-check` → PDF `Response` or a flash+redirect.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_cash_disbursements.py  (add; use existing fixtures/login helpers)
# Build a posted, check-paid CDV on a cash account with an active Default CD_CHECK layout+background,
# then assert the route behavior. Reuse whatever CDV/posted helper the suite already has; the key
# assertions:

def test_print_check_returns_pdf_when_ready(client, ready_check_cdv):
    resp = client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert len(resp.data) > 200

def test_print_check_blocks_cash_method(client, cash_method_cdv):
    resp = client.get(f'/cash-disbursements/{cash_method_cdv.id}/print-check', follow_redirects=True)
    assert b'not a check payment' in resp.data or resp.request.path.endswith(str(cash_method_cdv.id))

def test_print_check_blocks_missing_serial(client, check_cdv_no_number):
    resp = client.get(f'/cash-disbursements/{check_cdv_no_number.id}/print-check', follow_redirects=True)
    assert b'check number' in resp.data.lower()

def test_print_check_flashes_when_unconfigured(client, check_cdv_no_layout):
    # module on but no active CD_CHECK layout -> flash + redirect, never a voucher fallthrough / 500
    resp = client.get(f'/cash-disbursements/{check_cdv_no_layout.id}/print-check', follow_redirects=True)
    assert resp.status_code == 200
    assert b'check layout' in resp.data.lower()

def test_print_check_writes_audit(client, ready_check_cdv, db_session):
    from app.audit.models import AuditLog  # match the actual audit model import in the suite
    client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    entry = AuditLog.query.filter_by(action='print_check',
                                     record_identifier=ready_check_cdv.cdv_number).first()
    assert entry is not None
```

Add the fixtures near the top of the test module (or in `conftest.py`), building a CDV via the model with `payment_method='check'`, `status='posted'`, `check_number='00123'`, `total_amount=Decimal('1234.50')`, a `cash_account`, and (for `ready_check_cdv`) a `PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True, background_image=<a real small png under instance/uploads/preprinted>, fields_json=<one placed field>)` plus `module_enabled('preprinted_forms')` on. Mirror how `test_preprinted_forms.py` sets up an active layout + uploaded image.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_cash_disbursements.py -k print_check -v`
Expected: FAIL — 404 (route undefined).

- [ ] **Step 3: Implement the route**

```python
# app/cash_disbursements/views.py  (add near print_cdv)
@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print-check')
@login_required
def print_check(id):
    cdv = _get_cdv_or_404(id)  # unsaved voucher has no id -> cannot reach here

    from app.preprinted_forms.pdf import can_print, resolve_check_layout, render_preprinted
    from app.users.module_access import module_enabled
    from flask import Response

    if cdv.payment_method != 'check':
        flash('This voucher is not a check payment.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    if not module_enabled('preprinted_forms'):
        flash('Check printing is not enabled.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    if not can_print('CD_CHECK', cdv):
        flash('Printing this check is not allowed in its current status.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    if not cdv.check_number:
        flash('Enter the check number before printing the check.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))
    if not cdv.total_amount or float(cdv.total_amount) <= 0:
        flash('Cannot print a check for a zero or negative amount.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    layout = resolve_check_layout(cdv)
    if layout is None:
        flash('No check layout is configured for this cash/bank account.', 'error')
        return redirect(url_for('cash_disbursements.view', id=id))

    pdf_bytes = render_preprinted(layout, cdv)
    log_audit(module='cash_disbursements', action='print_check', record_id=cdv.id,
              record_identifier=cdv.cdv_number, old_values=None, new_values=None,
              notes=f'account_id={cdv.cash_account_id} check_no={cdv.check_number}')
    return Response(pdf_bytes, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="check-{cdv.cdv_number}.pdf"'})
```

(Confirm `log_audit` is already imported in this module; if not, add `from app.audit.utils import log_audit`.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/integration/test_cash_disbursements.py -k print_check -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add app/cash_disbursements/views.py tests/integration/test_cash_disbursements.py
git commit -m "feat(cdv): print_check route (account layout, gated, audited)"
```

---

### Task 7: "Print Check" button on the CDV detail

**Files:**
- Modify: `app/cash_disbursements/views.py` (`view()` — compute `check_layout_ready`)
- Modify: `app/cash_disbursements/templates/cash_disbursements/detail.html` (near the existing Print button)
- Test: `tests/integration/test_cash_disbursements.py`

**Interfaces:**
- Consumes: `resolve_check_layout`, `can_print`, `module_enabled`.
- Produces: template var `check_layout_ready: bool`; a gated "Print Check" link.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_cash_disbursements.py  (add)
def test_detail_shows_print_check_when_ready(client, ready_check_cdv):
    resp = client.get(f'/cash-disbursements/{ready_check_cdv.id}')
    assert b'Print Check' in resp.data   # positive case

def test_detail_hides_print_check_for_cash(client, cash_method_cdv):
    resp = client.get(f'/cash-disbursements/{cash_method_cdv.id}')
    assert b'Print Check' not in resp.data

def test_detail_hides_print_check_when_no_layout(client, check_cdv_no_layout):
    resp = client.get(f'/cash-disbursements/{check_cdv_no_layout.id}')
    assert b'Print Check' not in resp.data
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_cash_disbursements.py -k print_check_when -v` (plus the two hide tests)
Expected: FAIL — the positive test fails (no button rendered).

- [ ] **Step 3: Compute the flag + render the gated button**

```python
# app/cash_disbursements/views.py  — in view(), before render_template
from app.preprinted_forms.pdf import can_print, resolve_check_layout
from app.users.module_access import module_enabled
check_layout_ready = bool(
    cdv.payment_method == 'check'
    and module_enabled('preprinted_forms')
    and cdv.check_number
    and cdv.total_amount and float(cdv.total_amount) > 0
    and can_print('CD_CHECK', cdv)
    and resolve_check_layout(cdv) is not None
)
# pass check_layout_ready=check_layout_ready into render_template(...)
```

```html
{# app/cash_disbursements/templates/cash_disbursements/detail.html — beside the existing Print button #}
{% if check_layout_ready %}
<a href="{{ url_for('cash_disbursements.print_check', id=cdv.id) }}"
   target="_blank" rel="noopener noreferrer" class="btn btn-secondary">Print Check</a>
{% endif %}
```

(Use `{# #}` for any explanatory comment near this block — never `<!-- -->`.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/integration/test_cash_disbursements.py -k "print_check_when or print_check_for_cash or print_check_when_no_layout" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/cash_disbursements/views.py app/cash_disbursements/templates/cash_disbursements/detail.html tests/integration/test_cash_disbursements.py
git commit -m "feat(cdv): gated Print Check button on detail (only when check-ready)"
```

---

### Task 8: Per-account check designer (account selector + persist page dims)

**Files:**
- Modify: `app/preprinted_forms/views.py` (`designer`, `save`, `upload_image`, `toggle`, `_get_or_create_layout`)
- Modify: `app/preprinted_forms/templates/preprinted_forms/designer.html` (account selector for CD_CHECK)
- Test: `tests/integration/test_preprinted_forms.py`

**Interfaces:**
- Produces: designer/save/upload/toggle accept an optional `account_id` (query/form); `_get_or_create_layout(vt, account_id=None)` keyed by `(voucher_type, account_id)`; `save()` persists `page_width_mm`/`page_height_mm`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_preprinted_forms.py  (add)
def test_get_or_create_layout_is_account_scoped(db_session):
    from app.preprinted_forms.views import _get_or_create_layout
    d = _get_or_create_layout('CD_CHECK', account_id=None)
    a = _get_or_create_layout('CD_CHECK', account_id=5)
    from app import db; db.session.commit()
    assert d.id != a.id and d.account_id is None and a.account_id == 5

def test_save_persists_page_dimensions(client_logged_in_editor):
    # POST the designer save with page dims for the CD_CHECK Default; assert they persist.
    resp = client_logged_in_editor.post('/preprinted-forms/CD_CHECK/save', data={
        'fields_json': '[]', 'line_band_json': '{}',
        'page_width_mm': '178.00', 'page_height_mm': '84.00',
    }, follow_redirects=True)
    from app.preprinted_forms.models import PrintLayout
    layout = PrintLayout.query.filter_by(voucher_type='CD_CHECK', account_id=None).first()
    assert float(layout.page_width_mm) == 178.00 and float(layout.page_height_mm) == 84.00
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k "account_scoped or persists_page" -v`
Expected: FAIL — `_get_or_create_layout` takes no `account_id`; page dims not saved.

- [ ] **Step 3: Thread `account_id` + persist dims**

```python
# app/preprinted_forms/views.py
def _get_or_create_layout(vt, account_id=None):
    layout = PrintLayout.query.filter_by(voucher_type=vt, account_id=account_id).first()
    if layout is None:
        layout = PrintLayout(voucher_type=vt, account_id=account_id)
        db.session.add(layout)
        db.session.flush()
    return layout
```

In `designer`, `save`, `upload_image`, `toggle`: read `account_id = request.args.get('account_id', type=int)` (or `request.form.get` for POST) and pass it to `_get_or_create_layout(vt, account_id)` / the `filter_by`. Default `None` preserves current behavior for SI/CR/CD/AP/JV.

In `save()`, after the existing `fields_json`/`line_band_json` writes, persist dims:

```python
    for attr, key in (('page_width_mm', 'page_width_mm'), ('page_height_mm', 'page_height_mm')):
        raw = request.form.get(key)
        if raw:
            try:
                setattr(layout, attr, Decimal(raw))
            except (InvalidOperation, TypeError):
                pass  # keep existing dimension on a bad value
```

(Add `from decimal import Decimal, InvalidOperation` at the top of `views.py` if absent.)

- [ ] **Step 4: Add the account selector to the check designer**

In `designer.html`, when `vt == 'CD_CHECK'`, render a `<select>` of cash/bank accounts plus a "Default" option; changing it navigates to `?account_id=<id>` (or omits it for Default). Populate the options from a new `accounts` var the `designer` view passes when `vt == 'CD_CHECK'` (query the accounts usable as CDV cash accounts — mirror how the CDV form builds its cash-account choices). Keep the page dimension inputs (`page_width_mm`/`page_height_mm`) in the save form so Step 3's persistence has values to store.

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -k "account_scoped or persists_page" -v`
Expected: PASS.

- [ ] **Step 6: Verify the 5 existing overlays still design/save (regression)**

Run: `python -m pytest tests/integration/test_preprinted_forms.py -v`
Expected: PASS — SI/CR/CD/AP/JV designer/save/upload/toggle unaffected (`account_id` defaults to `None`).

- [ ] **Step 7: Commit**

```bash
git add app/preprinted_forms/ tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): per-account check designer + persist page dimensions"
```

---

### Task 9: Regression map + full-suite gate

**Files:**
- Modify: `projects/cas/.claude/regression-map.json`

- [ ] **Step 1: Add the shared preprinted files to the blast-radius map**

Add entries mapping `app/preprinted_forms/pdf.py` and `app/preprinted_forms/field_catalog.py` to the modules that depend on them (at minimum `cash_disbursements`; include the other overlay modules that have markers). Follow the existing JSON shape in the file.

- [ ] **Step 2: Run the affected module suites single-threaded (ownership + ordering)**

Run: `python -m pytest -m "cash_disbursements" -o addopts= -q` and `python -m pytest tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py -q`
Expected: PASS; no newly-broken vs the baseline in `memory/project-preexisting-test-failures.md`.

- [ ] **Step 3: Commit**

```bash
git add projects/cas/.claude/regression-map.json
git commit -m "chore(guard): map preprinted pdf/field_catalog into the regression set"
```

---

## Post-implementation (not code tasks)

- **Full suite + guard (user-invoked):** ask the user to run `/run-tests cas` and `/guard cas`; confirm no newly-broken vs baseline.
- **Manual physical sign-off (release gate):** upload a scan of the real check as the CD_CHECK background, position fields in the designer, set the true page dimensions, `Test Print` (background drawn via `render_preprinted(..., test=True)`), then print a real check on the client's printer/stock and verify alignment + that figures ↔ words ↔ posted-JE all tie out. Software tests cannot certify physical registration.
- **Open items to confirm** (from the spec): bank legal-amount wording format (`PESOS … ONLY`, ALL CAPS, protective asterisks); reprint confirm-modal need; per-bank paper sizes.

---

## Self-Review

**Spec coverage:**
- Separate check layout / print both → Task 3 (CD_CHECK slot) + Task 6 (route) + existing voucher route. ✓
- Print Check only when `payment_method=='check'` → Task 6 gate + Task 7 button. ✓
- Per-account with Default fallback → Task 2 (model) + Task 5 (resolution) + Task 8 (designer). ✓
- Configurable draft gate → Task 4 (`cd_check_print_access` + `can_print` arm). ✓
- No check on unsaved voucher → Task 6 (`_get_cdv_or_404`). ✓
- Audit each print → Task 6 (`log_audit`) + tested. ✓
- Option A keying → Tasks 2–3. ✓
- `save()` persists page dims → Task 8. ✓
- amount_in_words overflow + HALF_UP → Task 1. ✓
- Coverage-hole tests + stale set-assert → Task 3. ✓
- Regression map → Task 9. ✓
- Three-way tie-out / physical sign-off → Post-implementation gate. (The words↔figure tie-out is covered by Task 1's boundary suite; the words↔figure↔GL tie-out is a manual/audit-spirit gate — add an automated version opportunistically in Task 6 if the suite already builds a posted JE for the fixture.)

**Placeholder scan:** No TBD/TODO; each code step carries real code. Template/settings steps point to the exact sibling to mirror (`cd_print_access`, the existing designer form) rather than inventing unknown internals — acceptable because the pattern is named and greppable.

**Type consistency:** `resolve_check_layout(cdv)`, `can_print('CD_CHECK', cdv)`, `_get_or_create_layout(vt, account_id=None)`, `check_layout_ready`, route name `cash_disbursements.print_check`, setting key `cd_check_print_access` — used consistently across Tasks 4–8.
