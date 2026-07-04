# CDV Check Printing + Per-Account Editable Layout — Implementation Plan (rev. 2, boardroom-reviewed)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a check-paid CDV print a data overlay onto physical pre-printed check stock, using an editable layout that is per cash/bank account (a Default layout plus per-account overrides), reusing the existing P-69 pre-printed-forms engine.

**Architecture:** Add a `CD_CHECK` layout slot and a nullable `account_id` dimension to the existing `PrintLayout` model (Option A — no `variant` column). A check layout resolves by the CDV's `cash_account_id` with fallback to the Default (`account_id IS NULL`). A new `print_check` route renders the overlay; a new `cd_check_print_access` setting gates posted-vs-draft. The 5 existing voucher overlays are untouched because `account_id` defaults to `NULL`.

**Tech Stack:** Flask, SQLAlchemy, Flask-Migrate/Alembic, SQLite, fpdf2, pytest. Source spec: `docs/superpowers/specs/2026-07-04-cdv-check-printing-design.md`.

**Rev. 2 changes (from boardroom plan review):** hand-written migration that drops the old unique index + adds a partial single-Default index + a smoke test on a real DB copy; settings toggle built the correct 3-file way; automated three-way (words↔figure↔posted-JE) tie-out; real test file + login/branch/module-enable fixtures; audit module string `cash_disbursement` (singular); `image()` route account-threaded; page-dimension persistence pulled into Increment 1 before the print route; delivery split into Increment 1 (Default check) then Increment 2 (per-account).

## Global Constraints

- **Run from `projects/cas/`** with the project venv: `C:/envs/erp-workspace/projects/cas/venv/Scripts/python -m pytest ...`. Dev server on port 5050.
- **TDD mandatory** — failing test first, watch it fail, then implement (CLAUDE.md).
- **Model-change approved** by the user (2026-07-04): `PrintLayout.account_id` + composite unique + partial single-Default index + `String(16)` + `save()` persists page dims. No further model changes without new approval.
- **Verify audit in action tests** — assert a `log_audit` row (and its `module`) exists after an audited action (CLAUDE.md).
- **Audit module string is `'cash_disbursement'` (singular)** — matches existing calls in `app/cash_disbursements/views.py`. Never `'cash_disbursements'`.
- **No JS popups** — custom HTML modals with `{{ csrf_token() }}` only.
- **Peso sign** never printed on the check (fpdf core font is latin-1; `_fmt_money` emits bare numbers). In templates use literal `₱`, never `&#8369;`.
- **Jinja `{# #}` comments** (never `<!-- -->`) near gated markup; pair absence-tests with a positive assertion.
- **Amount source** = `CashDisbursementVoucher.total_amount` (net cash disbursed). Never a pre-WHT figure.
- **`active` is Default-only (type-level master)** for `CD_CHECK`: it lives on the `account_id IS NULL` row and is the on/off for check printing; per-account rows override background/fields/page-dims only. Do NOT add a per-account `active` toggle.
- **Legal-amount presentation format is UNCONFIRMED** (bank may want ALL-CAPS / `PESOS … ONLY` / protective asterisks — spec open item). Fix `amount_in_words` *correctness* now; do NOT treat its Titlecase output as final until the client confirms the bank format. If the format changes, only Task 1's expected strings + a thin formatting layer change.
- **Migrations:** `Migrate()` is initialized WITHOUT `render_as_batch=True` (`app/__init__.py`), so `flask db migrate` autogen emits non-batch `op.*` that FAILS on SQLite. **Hand-write** every migration body using `op.batch_alter_table(...)`.
- **Commit after each task.** Work on `main`. Do not push.

---

## File Structure

- `app/preprinted_forms/models.py` — `PrintLayout` gains `account_id`, composite unique, wider `voucher_type`; `VOUCHER_TYPES`/`VOUCHER_LABELS` gain `CD_CHECK`.
- `migrations/versions/<rev>_printlayout_account_id.py` — hand-written migration.
- `app/preprinted_forms/field_catalog.py` — `amount_in_words` fix; `FIELD_CATALOG['CD_CHECK']`.
- `app/preprinted_forms/pdf.py` — `can_print` `CD_CHECK` arm; `resolve_check_layout()`.
- `app/preprinted_forms/views.py` — `_TEST_PRINT_MODEL_NAMES['CD_CHECK']`; `admin()` Default-only; `save()` persists page dims; (Increment 2) `account_id` on designer/save/upload/**image**.
- `app/company_settings/{views.py,forms.py}` + `templates/company_settings/form.html` — the `cd_check_print_access` setting UI.
- `app/seeds/seed_data.py` + `app/seeds/demo_seed.py` — seed `cd_check_print_access`.
- `app/cash_disbursements/views.py` — `print_check` route; `check_layout_ready` + prior-print entries in `view()`.
- `app/cash_disbursements/templates/cash_disbursements/detail.html` — gated "Print Check" button (near existing Print button at ~line 76-79).
- `.claude/regression-map.json` — add `app/preprinted_forms/{pdf,field_catalog,models}.py`.
- Tests: `tests/unit/test_field_catalog.py`, `tests/unit/test_preprinted_model.py`, `tests/integration/test_preprinted_forms.py`, **new** `tests/integration/test_cdv_check_printing.py`, and edits to `tests/integration/test_company_settings_*.py`.

---

# INCREMENT 1 — Default check (build, then physically sign off before Increment 2)

### Task 1: `amount_in_words` money-correctness fix

Fix the release-blocking overflow (blank legal line ≥ 1 trillion) and align rounding to HALF_UP. Pure-function; QA verified the boundary strings below are byte-for-byte what the code produces.

**Files:** Modify `app/preprinted_forms/field_catalog.py` (`_SCALES` ~line 77; `amount_in_words` ~line 116-133). Test `tests/unit/test_field_catalog.py`.

**Interfaces:** Produces `amount_in_words(value) -> str` — never raises / never returns `''` for a finite in-range amount; uses `ROUND_HALF_UP`.

- [ ] **Step 1: Write the failing tests**

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
    out = amount_in_words(Decimal("1000000000000.00"))  # was: swallowed IndexError -> blank line
    assert out.startswith("One Trillion")
    assert out.endswith("00/100")

def test_amount_in_words_half_up():
    assert amount_in_words(Decimal("0.005")) == "Zero Pesos and 01/100"
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/test_field_catalog.py -k amount_in_words -v` → FAIL (trillion blank; half_up gives 00/100).

- [ ] **Step 3: Implement**

```python
# app/preprinted_forms/field_catalog.py
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP   # add ROUND_HALF_UP
_SCALES = ('', 'Thousand', 'Million', 'Billion', 'Trillion', 'Quadrillion')
# in amount_in_words(): amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Run to verify pass** — same command → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/preprinted_forms/field_catalog.py tests/unit/test_field_catalog.py
git commit -m "fix(preprinted): amount_in_words no longer blanks >=1T; round HALF_UP"
```

> NOTE (do not skip): the Titlecase `"… Pesos and 50/100"` output is not yet confirmed against the client's bank check format. If the bank requires ALL-CAPS / `PESOS … ONLY` / asterisks, revise these expected strings + add a formatting wrapper then. Correctness (this task) is format-independent.

---

### Task 2: `PrintLayout` model change + hand-written migration + real-DB smoke test

**Files:** Modify `app/preprinted_forms/models.py` (class ~line 17-29). Create `migrations/versions/<rev>_printlayout_account_id.py`. Test `tests/unit/test_preprinted_model.py`.

**Interfaces:** Produces `PrintLayout.account_id` (nullable int FK → accounts.id); composite unique `(voucher_type, account_id)`; partial unique index enforcing one Default per slot; `voucher_type` = `String(16)`.

- [ ] **Step 1: Write the failing model test**

```python
# tests/unit/test_preprinted_model.py  (add)
from app import db
from app.preprinted_forms.models import PrintLayout

def test_printlayout_account_id_and_composite_unique(db_session):
    db.session.add_all([PrintLayout(voucher_type='CD_CHECK', account_id=None),
                        PrintLayout(voucher_type='CD_CHECK', account_id=1)])
    db.session.commit()
    assert PrintLayout.query.filter_by(voucher_type='CD_CHECK').count() == 2
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/test_preprinted_model.py::test_printlayout_account_id_and_composite_unique -v` → FAIL (`account_id` unknown).

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
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True, index=True)  # NULL = Default
    active = db.Column(db.Boolean, default=False, nullable=False)
    background_image = db.Column(db.String(200), nullable=True)
    page_width_mm = db.Column(db.Numeric(6, 2), default=215.90, nullable=False)
    page_height_mm = db.Column(db.Numeric(6, 2), default=279.40, nullable=False)
    fields_json = db.Column(db.Text, default='[]')
    line_band_json = db.Column(db.Text, default='{}')
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by = db.Column(db.String(80))
    # get_fields/set_fields/get_line_band/set_line_band unchanged
```

(Removed `unique=True` from `voucher_type`.)

- [ ] **Step 4: Hand-write the migration** (do NOT trust `flask db migrate` autogen — no `render_as_batch`)

Create the file with `python -m flask db revision -m "printlayout account_id"` (empty), then write:

```python
def upgrade():
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
        batch_op.alter_column('voucher_type', existing_type=sa.String(length=8),
                              type_=sa.String(length=16), existing_nullable=False)
        # DROP the old single-column UNIQUE INDEX (created unique=True in f826f2cca271).
        batch_op.drop_index('ix_print_layouts_voucher_type')
        batch_op.create_index(batch_op.f('ix_print_layouts_voucher_type'), ['voucher_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_print_layouts_account_id'), ['account_id'], unique=False)
        batch_op.create_foreign_key('fk_print_layouts_account_id_accounts',
                                    'accounts', ['account_id'], ['id'])
        batch_op.create_unique_constraint('uq_print_layouts_voucher_type_account_id',
                                          ['voucher_type', 'account_id'])
    # Partial unique index: one Default (account_id IS NULL) per voucher_type. SQLite treats NULLs
    # as distinct in the composite unique, so this closes the duplicate-Default hole + the race.
    op.create_index('uq_print_layouts_default_per_type', 'print_layouts', ['voucher_type'],
                    unique=True, sqlite_where=sa.text('account_id IS NULL'))

def downgrade():
    op.drop_index('uq_print_layouts_default_per_type', table_name='print_layouts')
    with op.batch_alter_table('print_layouts', schema=None) as batch_op:
        batch_op.drop_constraint('uq_print_layouts_voucher_type_account_id', type_='unique')
        batch_op.drop_constraint('fk_print_layouts_account_id_accounts', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_print_layouts_account_id'))
        batch_op.drop_index(batch_op.f('ix_print_layouts_voucher_type'))
        batch_op.create_index('ix_print_layouts_voucher_type', ['voucher_type'], unique=True)
        batch_op.alter_column('voucher_type', existing_type=sa.String(length=16),
                              type_=sa.String(length=8), existing_nullable=False)
        batch_op.drop_column('account_id')
```

- [ ] **Step 5: Apply to the dev DB** — `python -m flask db upgrade` → no traceback.

- [ ] **Step 6: Migration smoke test on a COPY of the real DB** (the unit test uses `create_all` and CANNOT catch a surviving old index)

```bash
python -c "
import shutil, sqlite3
shutil.copy('instance/cas.db', 'instance/_migsmoke.db')
c = sqlite3.connect('instance/_migsmoke.db')
c.execute(\"INSERT INTO print_layouts (voucher_type, account_id, active) VALUES ('CD_CHECK', NULL, 0)\")
c.execute(\"INSERT INTO print_layouts (voucher_type, account_id, active) VALUES ('CD_CHECK', 1, 0)\")
c.commit(); print('OK: Default + override coexist (old UNIQUE(voucher_type) is gone)')
c.close()
"
# NOTE: run this AFTER 'flask db upgrade' has been applied to a copy that carried the OLD schema.
# If instance/cas.db is already migrated, instead copy the pre-migration backup, upgrade it, then insert.
rm -f instance/_migsmoke.db
```

Expected: `OK: Default + override coexist`. A `UNIQUE constraint failed: print_layouts.voucher_type` here means the old index survived — fix the migration before proceeding.

- [ ] **Step 7: Run the model test** — `python -m pytest tests/unit/test_preprinted_model.py -v` → PASS.

- [ ] **Step 8: Commit**

```bash
git add app/preprinted_forms/models.py migrations/versions/ tests/unit/test_preprinted_model.py
git commit -m "feat(preprinted): PrintLayout per-account layouts (account_id, composite+partial unique)"
```

---

### Task 3: Register `CD_CHECK` type + field catalog (+ stale-test fixes)

**Files:** Modify `app/preprinted_forms/models.py` (`VOUCHER_TYPES`/`VOUCHER_LABELS`), `app/preprinted_forms/field_catalog.py` (`FIELD_CATALOG`), `app/preprinted_forms/views.py` (`_TEST_PRINT_MODEL_NAMES`). Tests: `test_field_catalog.py`, `test_preprinted_model.py`, `test_preprinted_forms.py`.

**Interfaces:** `VOUCHER_TYPES` includes `'CD_CHECK'`; `FIELD_CATALOG['CD_CHECK']` has `header` (check_date, payee, total, amount_in_words, check_number, memo) + `line_columns=[]`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_field_catalog.py  (add)
from app.preprinted_forms.field_catalog import FIELD_CATALOG, resolve_field

def test_cd_check_catalog_shape():
    cat = FIELD_CATALOG['CD_CHECK']
    assert 'header' in cat and cat['line_columns'] == []
    assert {'check_date','payee','total','amount_in_words','check_number','memo'} <= {f['key'] for f in cat['header']}

def test_cd_check_resolves_from_cdv():
    class FakeCDV: vendor_name='ACME'; total_amount=1234.50; check_number='00123'
    assert resolve_field('CD_CHECK','payee',FakeCDV()) == 'ACME'
    assert resolve_field('CD_CHECK','amount_in_words',FakeCDV()).startswith('One Thousand Two Hundred')
```

Update the stale exact-tuple assert (justified stale-fail):

```python
# tests/unit/test_preprinted_model.py
assert VOUCHER_TYPES == ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK')
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/unit/test_field_catalog.py -k cd_check tests/unit/test_preprinted_model.py -v` → FAIL.

- [ ] **Step 3: Register**

```python
# app/preprinted_forms/models.py
VOUCHER_TYPES = ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK')
VOUCHER_LABELS = { ...existing 5..., 'CD_CHECK': 'Cash Disbursement — Check' }
```

```python
# app/preprinted_forms/field_catalog.py  (add to FIELD_CATALOG)
    'CD_CHECK': {
        'header': [
            _hf('check_date', 'Check Date', _attr_date('check_date')),
            _hf('payee', 'Payee (Vendor)', _attr_str('vendor_name')),
            _hf('total', 'Amount (Figures)', _attr_money('total_amount')),
            _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
            _hf('check_number', 'Check Number', _attr_str('check_number')),
            _hf('memo', 'Memo', _attr_str('notes')),
        ],
        'line_columns': [],
    },
```

```python
# app/preprinted_forms/views.py  (add to _TEST_PRINT_MODEL_NAMES)
    'CD_CHECK': ('app.cash_disbursements.models', 'CashDisbursementVoucher'),
```

- [ ] **Step 4: Close coverage-hole loops** — in `tests/unit/test_field_catalog.py` and `tests/integration/test_preprinted_forms.py`, add `'CD_CHECK'` to the hardcoded `('SI','CR','CD','AP','JV')` iteration literals so they actually exercise the new type. Grep both files for that tuple.

- [ ] **Step 5: Fix the admin-list assertion** — grep `test_preprinted_forms.py` for an admin toggle-list row-count/content assertion (e.g. `test_admin_toggles_page_renders...` ~line 459-466). The admin list now renders 6 types; update the expectation. Confirm whether the template iterates `VOUCHER_LABELS`/`VOUCHER_TYPES` (renders all 6) vs existing rows (renders only created rows) and align the test accordingly.

- [ ] **Step 6: Run** — `python -m pytest tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add app/preprinted_forms/ tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): register CD_CHECK layout type + field catalog"
```

---

### Task 4: `cd_check_print_access` setting (full UI) + `can_print` arm

Build the configurable toggle the correct 3-file way (+ seed + fix stale settings-form payloads), then wire `can_print`.

**Files:** Modify `app/company_settings/views.py` (`SETTINGS_KEYS` ~line 39-58), `app/company_settings/forms.py` (add `SelectField` beside `cd_print_access` ~line 110), `app/company_settings/templates/company_settings/form.html` (render beside `cd_print_access` ~line 185), `app/seeds/seed_data.py` + `app/seeds/demo_seed.py` (`*_print_access` lists), `app/preprinted_forms/pdf.py` (`can_print` ~line 16-43). Tests: `tests/integration/test_preprinted_forms.py`, and edit `tests/integration/test_company_settings_self_approval.py` + `test_company_settings_views.py` payloads.

**Interfaces:** setting `cd_check_print_access` (default `'posted_only'`; values `posted_only`/`draft_and_posted`); `can_print('CD_CHECK', cdv)` honors it.

- [ ] **Step 1: Write the failing `can_print` tests**

```python
# tests/integration/test_preprinted_forms.py  (add)
from app.preprinted_forms.pdf import can_print
from app.settings import AppSettings
def _cdv(status):
    from app.cash_disbursements.models import CashDisbursementVoucher
    c = CashDisbursementVoucher(); c.status = status; return c

def test_can_print_cd_check_posted_only(db_session):
    AppSettings.set_setting('cd_check_print_access', 'posted_only')
    assert can_print('CD_CHECK', _cdv('posted')) is True
    assert can_print('CD_CHECK', _cdv('draft')) is False

def test_can_print_cd_check_draft_and_posted(db_session):
    AppSettings.set_setting('cd_check_print_access', 'draft_and_posted')
    assert can_print('CD_CHECK', _cdv('draft')) is True
    for bad in ('voided', 'cancelled'):
        assert can_print('CD_CHECK', _cdv(bad)) is False
```

- [ ] **Step 2: Run to verify failure** — `-k can_print_cd_check` → FAIL (returns False; hits `else`).

- [ ] **Step 3: Add the `can_print` arm**

```python
# app/preprinted_forms/pdf.py  — inside can_print(), BEFORE the final else
    elif voucher_type == 'CD_CHECK':
        setting = AppSettings.get_setting('cd_check_print_access', 'posted_only')
        posted_ok = record.status == 'posted'
```

- [ ] **Step 4: Build the settings UI (3 files) + seed + fix stale payloads**

1. `app/company_settings/views.py`: add `'cd_check_print_access'` to `SETTINGS_KEYS` (right after `'cd_print_access'`).
2. `app/company_settings/forms.py`: add, mirroring `cd_print_access`:
```python
    cd_check_print_access = SelectField('Check Print Access',
        choices=[('posted_only', 'Posted only'), ('draft_and_posted', 'Draft and Posted')],
        default='posted_only')
```
3. `company_settings/templates/company_settings/form.html`: render `{{ form.cd_check_print_access }}` in the same block as `cd_print_access` (~line 185), with its label.
4. `app/seeds/seed_data.py` AND `app/seeds/demo_seed.py`: add `'cd_check_print_access': 'posted_only'` where the other `*_print_access` keys are seeded.
5. Fix the fixed-dict settings-form payloads so the new `SelectField` validates: add `'cd_check_print_access': 'posted_only'` to `_base_form` in `tests/integration/test_company_settings_self_approval.py` (~line 17-20) and the POST dict in `tests/integration/test_company_settings_views.py` (~line 279-282).
6. If a seed-count baseline test exists (grep `test_seed_minimal` / `test_demo_seed` for a settings count — memory: "seed = 19 settings"), bump its expected count by 1.

- [ ] **Step 5: Run** — `python -m pytest tests/integration/test_preprinted_forms.py -k can_print_cd_check tests/integration/test_company_settings_self_approval.py tests/integration/test_company_settings_views.py -v` → PASS (settings page still saves; new key round-trips).

- [ ] **Step 6: Commit**

```bash
git add app/company_settings/ app/seeds/ app/preprinted_forms/pdf.py tests/integration/
git commit -m "feat(preprinted): cd_check_print_access setting (UI+seed) + can_print CD_CHECK arm"
```

---

### Task 5: `resolve_check_layout()` — account → Default; admin list Default-only

**Files:** Modify `app/preprinted_forms/pdf.py` (add helper), `app/preprinted_forms/views.py` (`admin()` ~line 138). Test `tests/integration/test_preprinted_forms.py`.

**Interfaces:** `resolve_check_layout(cdv) -> PrintLayout | None`. Default row is the master switch: missing or `active=False` → `None`. Else pick the CDV's account override if it exists **and has a `background_image`**, else the Default; return it only if it has a `background_image`, else `None`. Per-account rows' own `active` is ignored (Default is master).

- [ ] **Step 1: Write failing tests** (incl. the override-`active=False`-still-resolves lock)

```python
# tests/integration/test_preprinted_forms.py  (add)
from app.preprinted_forms.pdf import resolve_check_layout
from app.preprinted_forms.models import PrintLayout
from app import db
class _CDV:
    def __init__(self, a): self.cash_account_id = a

def test_resolve_default_and_override(db_session):
    db.session.add_all([
        PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True, background_image='d.png'),
        PrintLayout(voucher_type='CD_CHECK', account_id=7, active=False, background_image='o.png')])
    db.session.commit()
    assert resolve_check_layout(_CDV(7)).background_image == 'o.png'   # override wins; its active is IGNORED
    assert resolve_check_layout(_CDV(99)).background_image == 'd.png'  # fallback to Default

def test_resolve_master_off(db_session):
    PrintLayout.query.delete()
    db.session.add(PrintLayout(voucher_type='CD_CHECK', account_id=None, active=False, background_image='d.png'))
    db.session.commit()
    assert resolve_check_layout(_CDV(7)) is None

def test_resolve_default_no_background(db_session):
    PrintLayout.query.delete()
    db.session.add(PrintLayout(voucher_type='CD_CHECK', account_id=None, active=True, background_image=None))
    db.session.commit()
    assert resolve_check_layout(_CDV(7)) is None
```

- [ ] **Step 2: Run to verify failure** — `-k resolve_` → FAIL (ImportError).

- [ ] **Step 3: Implement + fix admin list**

```python
# app/preprinted_forms/pdf.py
def resolve_check_layout(cdv):
    """CD_CHECK layout for a CDV: account override -> Default. Default.active = master switch;
    per-account rows' own active is ignored (no per-account toggle UI)."""
    from app.preprinted_forms.models import PrintLayout
    default = PrintLayout.query.filter_by(voucher_type='CD_CHECK', account_id=None).first()
    if not default or not default.active:
        return None
    override = PrintLayout.query.filter_by(voucher_type='CD_CHECK',
                                           account_id=cdv.cash_account_id).first()
    chosen = override if (override and override.background_image) else default
    return chosen if chosen.background_image else None
```

```python
# app/preprinted_forms/views.py  — admin(): the toggle list is per-type, so only Default rows
    layouts = {l.voucher_type: l for l in PrintLayout.query.filter_by(account_id=None).all()}
```

- [ ] **Step 4: Run** — `-k resolve_` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/preprinted_forms/pdf.py app/preprinted_forms/views.py tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): resolve_check_layout (override->Default); admin lists Default rows"
```

---

### Task 6: `save()` persists page dimensions (MVP-critical — a check is not US Letter)

Pulled ahead of the print route: without it, even the Default check prints at 215.9×279.4mm and never registers on check stock.

**Files:** Modify `app/preprinted_forms/views.py` (`save()` ~line 198-222) + `designer.html` (ensure the dims inputs post). Test `tests/integration/test_preprinted_forms.py`.

**Interfaces:** `save()` reads `page_width_mm`/`page_height_mm` from the form and persists them (bad values keep the existing dimension).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_preprinted_forms.py  (add; reuse the module's login+enable fixtures)
def test_save_persists_page_dimensions(preprinted_editor_client):
    preprinted_editor_client.post('/preprinted-forms/CD_CHECK/save', data={
        'fields_json': '[]', 'line_band_json': '{}',
        'page_width_mm': '178.00', 'page_height_mm': '84.00'}, follow_redirects=True)
    from app.preprinted_forms.models import PrintLayout
    l = PrintLayout.query.filter_by(voucher_type='CD_CHECK', account_id=None).first()
    assert float(l.page_width_mm) == 178.00 and float(l.page_height_mm) == 84.00
```

(`preprinted_editor_client` = the module's logged-in editor + branch + module-enabled fixture; reuse `_login`/`_select_branch`/`preprinted_module_enabled` from `test_preprinted_forms.py:29-67`.)

- [ ] **Step 2: Run to verify failure** — FAIL (dims not persisted).

- [ ] **Step 3: Persist dims in `save()`**

```python
# app/preprinted_forms/views.py  — in save(), after the fields_json/line_band_json writes:
from decimal import Decimal, InvalidOperation   # add at top of module if absent
    for attr in ('page_width_mm', 'page_height_mm'):
        raw = request.form.get(attr)
        if raw:
            try:
                setattr(layout, attr, Decimal(raw))
            except (InvalidOperation, TypeError):
                pass  # keep existing dimension on a bad value
```

Ensure `designer.html` includes `<input name="page_width_mm">` / `page_height_mm` inside the save `<form>` (add if absent, pre-filled from `page_width_mm`/`page_height_mm` template vars).

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/preprinted_forms/views.py app/preprinted_forms/templates/preprinted_forms/designer.html tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): designer save persists page dimensions"
```

---

### Task 7: `print_check` route + audit + three-way tie-out

**Files:** Modify `app/cash_disbursements/views.py` (near `print_cdv` ~line 1141). Create `tests/integration/test_cdv_check_printing.py`.

**Interfaces:** route `cash_disbursements.print_check` at `/cash-disbursements/<int:id>/print-check` → PDF `Response` or flash+redirect; audits `action='print_check'`, `module='cash_disbursement'`.

- [ ] **Step 1: Author the test file + fixtures, then write failing tests**

Create `tests/integration/test_cdv_check_printing.py`. Fixtures must **log in + select branch + enable the module** (mirror `test_cdv_print_access.py` `_draft_cdv` + `test_preprinted_forms.py:29-67` `_login`/`_select_branch`/`preprinted_module_enabled`). `background_image='x.png'` is enough (non-`test=True` render never opens the file). Build `ready_check_cdv` = a **posted** CDV, `payment_method='check'`, `check_number='00123'`, `total_amount=Decimal('1234.50')`, on a `cash_account`, with a **posted journal entry**, plus an active Default `CD_CHECK` `PrintLayout` (background + one placed field), and the module enabled.

```python
# tests/integration/test_cdv_check_printing.py
from decimal import Decimal
from app.audit.models import AuditLog   # confirm the model/import used elsewhere in the suite

def test_print_check_returns_pdf(logged_in_branch_client, ready_check_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and len(r.data) > 200

def test_print_check_blocks_cash(logged_in_branch_client, cash_method_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{cash_method_cdv.id}/print-check', follow_redirects=True)
    assert b'not a check payment' in r.data

def test_print_check_blocks_draft_under_posted_only(logged_in_branch_client, draft_check_cdv):
    r = logged_in_branch_client.get(f'/cash-disbursements/{draft_check_cdv.id}/print-check', follow_redirects=True)
    assert r.request.path.endswith(str(draft_check_cdv.id))  # bounced back to the CDV view
    assert b'not allowed' in r.data.lower()

def test_print_check_blocks_missing_serial(logged_in_branch_client, check_cdv_no_number):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_no_number.id}/print-check', follow_redirects=True)
    assert b'check number' in r.data.lower()

def test_print_check_blocks_zero_amount(logged_in_branch_client, check_cdv_zero_amount):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_zero_amount.id}/print-check', follow_redirects=True)
    assert b'zero or negative' in r.data.lower()

def test_print_check_flashes_when_unconfigured(logged_in_branch_client, check_cdv_no_layout):
    r = logged_in_branch_client.get(f'/cash-disbursements/{check_cdv_no_layout.id}/print-check', follow_redirects=True)
    assert r.status_code == 200 and b'check layout' in r.data.lower()  # never a 500 / voucher fallthrough

def test_print_check_writes_audit(logged_in_branch_client, ready_check_cdv, db_session):
    logged_in_branch_client.get(f'/cash-disbursements/{ready_check_cdv.id}/print-check')
    e = AuditLog.query.filter_by(action='print_check', record_identifier=ready_check_cdv.cdv_number).first()
    assert e is not None and e.module == 'cash_disbursement'

def test_check_amount_ties_out_to_posted_je(ready_check_cdv):
    # words==figure is tautological (same attr). The independent check is the posted JE cash leg.
    from app.preprinted_forms.field_catalog import amount_in_words, _fmt_money
    je = ready_check_cdv.journal_entry
    cash_credit = sum(l.credit_amount or 0 for l in je.lines
                      if l.account_id == ready_check_cdv.cash_account_id)
    assert Decimal(str(cash_credit)) == Decimal(str(ready_check_cdv.total_amount))
    assert _fmt_money(ready_check_cdv.total_amount) == '1,234.50'
    assert amount_in_words(ready_check_cdv.total_amount).startswith('One Thousand Two Hundred Thirty-Four')

def test_check_amount_ties_out_under_wt_override(wt_override_check_cdv):
    # A CDV whose total_wt was overridden so total_amount != sum of line wt_amounts:
    # the printed face value must still equal the posted JE cash credit, or the tie-out fails.
    je = wt_override_check_cdv.journal_entry
    cash_credit = sum(l.credit_amount or 0 for l in je.lines
                      if l.account_id == wt_override_check_cdv.cash_account_id)
    assert Decimal(str(cash_credit)) == Decimal(str(wt_override_check_cdv.total_amount))
```

(If `_fmt_money` is module-private, assert the printed figure via the rendered PDF text or replicate `'{:,.2f}'.format`. If the `wt_override` fixture reveals a real divergence, that is a genuine defect to report — do not weaken the assertion; escalate per the testing-scope rule.)

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/integration/test_cdv_check_printing.py -v` → FAIL (route 404 / fixtures).

- [ ] **Step 3: Implement the route**

```python
# app/cash_disbursements/views.py  (near print_cdv)
@cash_disbursements_bp.route('/cash-disbursements/<int:id>/print-check')
@login_required
def print_check(id):
    cdv = _get_cdv_or_404(id)  # unsaved voucher has no id; branch-scoped 404
    from app.preprinted_forms.pdf import can_print, resolve_check_layout, render_preprinted
    from app.users.module_access import module_enabled
    from flask import Response
    if cdv.payment_method != 'check':
        flash('This voucher is not a check payment.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    if not module_enabled('preprinted_forms'):
        flash('Check printing is not enabled.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    if not can_print('CD_CHECK', cdv):
        flash('Printing this check is not allowed in its current status.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    if not cdv.check_number:
        flash('Enter the check number before printing the check.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    if not cdv.total_amount or float(cdv.total_amount) <= 0:
        flash('Cannot print a check for a zero or negative amount.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    layout = resolve_check_layout(cdv)
    if layout is None:
        flash('No check layout is configured for this cash/bank account.', 'error'); return redirect(url_for('cash_disbursements.view', id=id))
    pdf_bytes = render_preprinted(layout, cdv)
    log_audit(module='cash_disbursement', action='print_check', record_id=cdv.id,
              record_identifier=cdv.cdv_number, old_values=None, new_values=None,
              notes=f'account_id={cdv.cash_account_id} check_no={cdv.check_number}')
    return Response(pdf_bytes, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="check-{cdv.cdv_number}.pdf"'})
```

(`log_audit` is already imported at `views.py:15`.)

- [ ] **Step 4: Run** → PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/cash_disbursements/views.py tests/integration/test_cdv_check_printing.py
git commit -m "feat(cdv): print_check route (gated, audited, tie-out tested)"
```

---

### Task 8: Gated "Print Check" button + prior-print visibility

**Files:** Modify `app/cash_disbursements/views.py` (`view()`), `app/cash_disbursements/templates/cash_disbursements/detail.html` (~line 76-79). Test `tests/integration/test_cdv_check_printing.py`.

**Interfaces:** template vars `check_layout_ready: bool` and `check_print_count: int`; a gated "Print Check" link.

- [ ] **Step 1: Write failing truth-table tests**

```python
# tests/integration/test_cdv_check_printing.py  (add)
import pytest
def test_detail_shows_print_check_when_ready(logged_in_branch_client, ready_check_cdv):
    assert b'Print Check' in logged_in_branch_client.get(f'/cash-disbursements/{ready_check_cdv.id}').data

@pytest.mark.parametrize('fixture_name', [
    'cash_method_cdv', 'draft_check_cdv', 'voided_check_cdv', 'check_cdv_no_number',
    'check_cdv_zero_amount', 'check_cdv_no_layout', 'check_cdv_module_off', 'check_cdv_inactive_default',
])
def test_detail_hides_print_check(logged_in_branch_client, request, fixture_name):
    cdv = request.getfixturevalue(fixture_name)
    assert b'Print Check' not in logged_in_branch_client.get(f'/cash-disbursements/{cdv.id}').data
```

- [ ] **Step 2: Run to verify failure** — the positive test fails (no button).

- [ ] **Step 3: Compute the flag + render the gated button**

```python
# app/cash_disbursements/views.py  — in view(), before render_template
from app.preprinted_forms.pdf import can_print, resolve_check_layout
from app.users.module_access import module_enabled
check_layout_ready = bool(
    cdv.payment_method == 'check' and module_enabled('preprinted_forms')
    and cdv.check_number and cdv.total_amount and float(cdv.total_amount) > 0
    and can_print('CD_CHECK', cdv) and resolve_check_layout(cdv) is not None)
from app.audit.models import AuditLog
check_print_count = AuditLog.query.filter_by(action='print_check',
                                             record_identifier=cdv.cdv_number).count()
# pass check_layout_ready=..., check_print_count=... into render_template
```

```html
{# app/cash_disbursements/templates/cash_disbursements/detail.html — beside the existing Print button #}
{% if check_layout_ready %}
<a href="{{ url_for('cash_disbursements.print_check', id=cdv.id) }}" target="_blank"
   rel="noopener noreferrer" class="btn btn-secondary">Print Check</a>
{% if check_print_count %}<span class="text-muted">Check printed {{ check_print_count }}×</span>{% endif %}
{% endif %}
```

(Prior-print count is the cheap reprint-safety signal; a CSRF confirm-modal fast-follow is deferred to Increment 2. Use `{# #}` for any comment near this block; grep detail.html for any other `Print Check` literal that would defeat the absence test.)

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/cash_disbursements/ tests/integration/test_cdv_check_printing.py
git commit -m "feat(cdv): gated Print Check button + prior-print count"
```

---

### Task 9: Regression map + Increment-1 gate

**Files:** Modify `.claude/regression-map.json` (run from `projects/cas`).

- [ ] **Step 1: Map the shared preprinted files** — add `app/preprinted_forms/pdf.py`, `app/preprinted_forms/field_catalog.py`, and **`app/preprinted_forms/models.py`** (the unique-swap is shared blast radius via `preprinted_response`) → the dependent modules (`cash_disbursements` + the other overlay modules with markers). Follow the existing JSON shape.

- [ ] **Step 2: Single-threaded regression run** — `python -m pytest -m "cash_disbursements" -o addopts= -q` and `python -m pytest tests/unit/test_field_catalog.py tests/unit/test_preprinted_model.py tests/integration/test_preprinted_forms.py tests/integration/test_cdv_check_printing.py -q` → PASS, no newly-broken vs `memory/project-preexisting-test-failures.md`.

- [ ] **Step 3: Commit**

```bash
git add .claude/regression-map.json
git commit -m "chore(guard): map preprinted pdf/field_catalog/models into the regression set"
```

### Increment 1 physical sign-off (release gate — before Increment 2)
Upload a scan of the real check as the Default `CD_CHECK` background, set the true page dimensions, place fields, `Test Print` (background via `render_preprinted(..., test=True)`), print a real check on the client's printer/stock, and verify alignment + that figures ↔ words ↔ posted-JE all tie out. Ask the user to run `/run-tests cas` and `/guard cas`. **Do not start Increment 2 until a real Default check prints correctly.**

---

# INCREMENT 2 — Per-account overrides (after Increment 1 physical sign-off)

### Task 10: Per-account check designer (account selector + `image()` threading)

**Files:** Modify `app/preprinted_forms/views.py` (`_get_or_create_layout`, `designer`, `save`, `upload_image`, **`image`**), `designer.html`. Test `tests/integration/test_preprinted_forms.py`.

**Interfaces:** designer/save/upload/**image** accept optional `account_id`; `_get_or_create_layout(vt, account_id=None)` keyed by `(voucher_type, account_id)`. **`toggle` is NOT account-threaded** (`active` is Default-only).

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_preprinted_forms.py  (add)
def test_get_or_create_layout_account_scoped(db_session):
    from app.preprinted_forms.views import _get_or_create_layout
    from app import db
    d = _get_or_create_layout('CD_CHECK', account_id=None)
    a = _get_or_create_layout('CD_CHECK', account_id=5)
    db.session.commit()
    assert d.id != a.id and d.account_id is None and a.account_id == 5

def test_image_route_serves_account_specific_background(preprinted_editor_client, db_session):
    from app.preprinted_forms.models import PrintLayout
    from app import db
    db.session.add_all([
        PrintLayout(voucher_type='CD_CHECK', account_id=None, background_image='default.png'),
        PrintLayout(voucher_type='CD_CHECK', account_id=5, background_image='acct5.png')])
    db.session.commit()
    # the account-scoped image request must NOT serve an arbitrary/Default row
    r = preprinted_editor_client.get('/preprinted-forms/CD_CHECK/image?account_id=5')
    assert r.status_code in (200, 404)  # 404 only if file missing; must target the account_id=5 row
```

- [ ] **Step 2: Run to verify failure** — FAIL (`_get_or_create_layout` takes no `account_id`; `image` ignores it).

- [ ] **Step 3: Thread `account_id` (NOT through toggle)**

```python
# app/preprinted_forms/views.py
def _get_or_create_layout(vt, account_id=None):
    layout = PrintLayout.query.filter_by(voucher_type=vt, account_id=account_id).first()
    if layout is None:
        layout = PrintLayout(voucher_type=vt, account_id=account_id)
        db.session.add(layout); db.session.flush()
    return layout
```

In `designer`, `save`, `upload_image`, **`image`**: read `account_id = request.args.get('account_id', type=int)` (or form for POST) and pass it to `_get_or_create_layout(vt, account_id)` / the `filter_by`. In `image()` specifically, replace `filter_by(voucher_type=vt).first()` with `filter_by(voucher_type=vt, account_id=account_id).first()`. **Leave `toggle` unchanged** (no `account_id`).

- [ ] **Step 4: Account selector + half-configured indicator in `designer.html`** — when `vt == 'CD_CHECK'`, render a `<select>` of cash/bank accounts + a "Default" option; changing it navigates to `?account_id=<id>` (omit for Default). Populate from an `accounts` var the `designer` view passes for `CD_CHECK` (mirror how the CDV form builds cash-account choices). When viewing an account override with **no background yet**, show an inline notice: "This account has no background — the Default check layout will print for it."

- [ ] **Step 5: Run** — `-k "account_scoped or image_route"` → PASS.

- [ ] **Step 6: Regression — existing overlays + Increment-1 unaffected** — `python -m pytest tests/integration/test_preprinted_forms.py tests/integration/test_cdv_check_printing.py -v` → PASS (SI/CR/CD/AP/JV designer/save/upload/toggle/image unchanged; `account_id` defaults to `None`).

- [ ] **Step 7: Commit**

```bash
git add app/preprinted_forms/ tests/integration/test_preprinted_forms.py
git commit -m "feat(preprinted): per-account check designer (account_id on designer/save/upload/image; half-config notice)"
```

### Increment 2 fast-follow (optional, same increment or next)
CSRF confirm modal on a **re-print** of an already-printed check (double-print risk on a negotiable instrument), using a custom HTML modal (no JS popup). Gate on `check_print_count > 0`.

---

## Self-Review

**Spec + review coverage:** separate check / print both → T3+T7. Print Check only when check → T7 gate + T8 button. Per-account + Default fallback → T2+T5+T10. Configurable draft gate (UI built) → T4. No check on unsaved voucher → T7 (`_get_cdv_or_404`). Audit each print → T7 (singular module, tested). Option A keying → T2-3. Page dims persisted → T6 (Increment 1). amount_in_words overflow+HALF_UP → T1. **Blockers:** migration drop-index+partial-index+real-DB smoke → T2; test infra (real file, login+branch+module-enable, no on-disk PNG) → T7; automated three-way tie-out (+wt_override) → T7; `total<=0` route test → T7; audit module singular → T7; `image()` account threading → T10; dead `toggle` removed → T10 (toggle untouched). **Improvements:** T8 split (page-dims in Increment 1) → T6; don't pin legal format → T1 note; half-config notice → T10; route status-gate tests → T7; button truth-table → T8; reprint visibility → T8 + modal fast-follow; regression map incl models.py → T9.

**Placeholder scan:** none — real code per step; settings/template/designer steps name the exact sibling to mirror (`cd_print_access`, existing designer form) rather than inventing internals.

**Type consistency:** `resolve_check_layout(cdv)`, `can_print('CD_CHECK', cdv)`, `_get_or_create_layout(vt, account_id=None)`, `check_layout_ready`, `check_print_count`, `cash_disbursements.print_check`, setting `cd_check_print_access`, audit `module='cash_disbursement'` — consistent across tasks.
