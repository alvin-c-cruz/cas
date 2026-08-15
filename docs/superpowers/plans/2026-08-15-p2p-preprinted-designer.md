# P2P Pre-printed Designer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client print Purchase Requisitions, Purchase Orders and Receiving Reports onto their own pre-printed stationery, using the same drag-drop layout designer the other eight voucher types already have.

**Architecture:** One shared core (`app/common/preprinted_base.py` + `app/static/js/preprinted_designer.js`) replaces what is currently copy-pasted eight times; PR/PO/RR each declare only their own fields, columns and setting key against it. The eight existing layouts are deliberately left untouched.

**Tech Stack:** Flask 3, SQLAlchemy 2.0, SQLite, Jinja2, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-p2p-print-parity-design.md`
**Closes (partially):** `BUG-P2P-LIST-DETAIL-VOUCHER-UX-PARITY-GAP` — the pre-printed half of the print surface.

## Scope split

The spec covers two independent pieces. This plan is **piece 1 of 2**:

- **This plan — the missing FEATURE.** PR/PO/RR were never wired into the pre-printed layout
  designer at all. Shared base, shared designer JS/CSS, three layout declarations, three
  `print_preprinted.html` templates, print routing and gating.
- **A follow-up plan — styling parity.** A branded `print.html` for PO and RR (mirroring PR's, which
  is already done), `list_print.html` for all three, and extraction of PR's letterhead/signatory
  markup into a shared partial. Independently shippable; not required by anything here.

## Global Constraints

- Work in a worktree cut from the INNER repo: `git -C projects/cas worktree add ../wt-p2p-preprinted -b feat/p2p-preprinted-designer main`. Never commit to `main`.
- Run tests with the project venv: `C:/envs/erp-workspace/projects/cas/venv/Scripts/python.exe -m pytest ... -q --no-cov`. Copy `.env` into the worktree first.
- Use `db.session.get(Model, id)` / `db.get_or_404(Model, id)`. NEVER `Model.query.get(...)` — it emits `LegacyAPIWarning` and the suite is at zero warnings.
- Money/quantity arithmetic uses `Decimal`, never float.
- Dates use `app.utils.ph_now` (Philippine time), never naive `datetime.now()`.
- Use Jinja `{# #}` comments, never `<!-- -->`, near gated markup: HTML comments are served and defeat absence assertions.
- No JS `confirm()`/`alert()`/`prompt()`.
- Every layout save calls `log_audit` — the existing modules do, and an unaudited settings write on a client's stationery alignment is a real gap.
- After editing anything under `app/static/`, bump `?v=N` on EVERY template that loads it.
- **Do not modify the eight existing `preprinted_layout.py` files or their designer JS/CSS.** They are client-facing and pixel-sensitive on real stationery. This plan adds a base alongside them; migrating them is a separate, later decision.
- Peso sign: literal `₱` (U+20B1), never `&#8369;`.

## Reference implementation

`app/sales_orders/` is the closest analogue (a non-posting document) and is the pattern to mirror
throughout:

- `app/sales_orders/preprinted_layout.py` — 275 lines; public API is `sanitize_layout(raw)`,
  `get_layout(branch_id=None)`, `save_layout(raw, username, branch_id=None)`; private helpers
  `_clamp`, `_clean_box`, `_clean_columns`, `_clean_extras`, `_layout_key`.
- `app/sales_orders/views.py:894` `print_so` — reads `so_print_form` (`current` / `preprinted` /
  `hidden`) and renders accordingly.
- `app/sales_orders/views.py:965` `save_print_layout` — `POST`, `has_full_access` only.
- `app/sales_orders/templates/sales_orders/print_preprinted.html` — 157 lines.
- `app/static/js/so_preprinted_designer.js` (431 lines), `app/static/css/so_preprinted_designer.css` (15 lines).

**Layouts are PER BRANCH.** `_layout_key(branch_id)` returns `'<key>:<branch_id>'`, falling back to
the bare key when `branch_id is None` (legacy back-compat). Preserve that exactly.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/common/preprinted_base.py` | Canvas, fonts, clamps, sanitiser, get/save factory | Create |
| `app/static/js/preprinted_designer.js` | Parameterised designer core | Create |
| `app/static/css/preprinted_designer.css` | Shared designer styles | Create |
| `app/purchase_orders/preprinted_layout.py` | PO fields/columns/key only | Create |
| `app/purchase_requests/preprinted_layout.py` | PR fields/columns/key only | Create |
| `app/receiving_reports/preprinted_layout.py` | RR fields/columns/key only | Create |
| `app/*/templates/*/print_preprinted.html` | Overlay template (×3) | Create |
| `app/*/views.py` | Print routing + layout save (×3) | Modify |
| `tests/unit/test_preprinted_base.py` | Sanitiser contract | Create |
| `tests/integration/test_p2p_preprinted_print.py` | Routing + gating (×3) | Create |

---

### Task 1: Approved mockup of the designer canvas

**Files:**
- Create: `docs/mockups/2026-08-15-p2p-preprinted-designer.html`

**Interfaces:**
- Consumes: nothing.
- Produces: an approved visual reference the later template tasks build against.

This project's convention is **mockup-first for UI-bearing work**: a self-contained static HTML
mockup, reviewed in a browser and approved, BEFORE any Jinja is written. Placement is cheap to
change here and expensive once three modules render it.

- [ ] **Step 1: Build the mockup**

Create `docs/mockups/2026-08-15-p2p-preprinted-designer.html` as ONE standalone file — inline CSS,
inline dummy data, no app, no build step, opens by double-click.

It must show the **Purchase Order** case (the richest of the three) on the continuous-form canvas:

- a 912×1008 canvas at 96dpi with the 48px safe-margin guide visible
- the ten PO fields positioned as draggable boxes: `po_no, order_date, expected_date, vendor_name,
  vendor_tin, vendor_address, payment_terms, reference, vat_treatment, total_amount`
- a line-item band with the seven columns: `line_number, product, description, quantity, uom,
  unit_price, amount`, showing 3 dummy rows
- the editor chrome: field show/hide strip, font picker, paper toggle (continuous / letter), date
  format picker, and the three signatory text blocks (Preparer / Checker / Approver)
- a clear visual distinction between **edit mode** (boxes outlined, labels shown) and **print
  preview** (data only, no chrome) — this is the whole point of an overlay for pre-printed stock

Use realistic dummy values (a real-looking PO number, vendor name, peso amounts with `₱`).

- [ ] **Step 2: Review it in a browser and get approval**

Open the file in a browser and show it to the human partner. **Do not proceed to Task 2 until they
approve it.** If they request changes, change the mockup — not the plan — and show it again.

- [ ] **Step 3: Commit**

```bash
git add docs/mockups/2026-08-15-p2p-preprinted-designer.html
git commit -m "docs(mockup): P2P pre-printed designer canvas"
```

---

### Task 2: The shared layout base

**Files:**
- Create: `app/common/preprinted_base.py`
- Test: `tests/unit/test_preprinted_base.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CANVAS_W = 912`, `CANVAS_H = 1008`, `SAFE_MARGIN = 48`
  - `FONT_MIN, FONT_MAX = 6, 72`; `WIDTH_MIN, WIDTH_MAX = 10, 912`; `ROW_MIN, ROW_MAX = 8, 80`
  - `MAX_EXTRAS = 50`
  - `FONT_GROUPS`, `ALLOWED_FONTS`, `ALLOWED_PAPERS`, `PAPER_SIZES`, `PAPER_LABELS`,
    `DATE_FORMATS`, `ALLOWED_DATE_FORMATS`, `TEXT_KEYS`, `TEXT_LABELS`, `TEXT_MAXLEN`
  - `build_layout_api(setting_key, field_keys, default_layout, audit_module, audit_identifier)`
    returning `(sanitize_layout, get_layout, save_layout)`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_preprinted_base.py`:

```python
"""The shared pre-printed layout core.

This carries the highest test weight in the arc: a defect here breaks all three
consuming modules at once, and it is the code that decides what a client's
saved stationery alignment looks like after an upgrade.
"""
import json

import pytest

from app.common import preprinted_base as base

pytestmark = [pytest.mark.unit]

FIELD_KEYS = ['doc_no', 'doc_date']

DEFAULT = {
    'paper': 'continuous',
    'dateFormat': 'ymd',
    'page': {'fontFamily': base.ALLOWED_FONTS[0]},
    'fields': {
        'doc_no': {'x': 100, 'y': 100, 'w': 200, 'fontSize': 10, 'bold': False, 'hidden': False},
        'doc_date': {'x': 300, 'y': 100, 'w': 120, 'fontSize': 10, 'bold': False, 'hidden': False},
    },
    'lineItems': {'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False, 'columns': {}},
    'extras': [],
    'texts': {k: '' for k in base.TEXT_KEYS},
}


@pytest.fixture
def api():
    return base.build_layout_api('test_preprinted_layout', FIELD_KEYS, DEFAULT,
                                 'test_module', 'test_preprinted_layout')


class TestTheSanitiserRejectsJunk:

    def test_an_unknown_top_level_key_is_dropped(self, api):
        sanitize, _, _ = api
        out = sanitize({'paper': 'letter', 'evil': 'payload'})
        assert 'evil' not in out

    def test_an_unknown_field_key_is_dropped(self, api):
        """A stored layout naming a field this document does not have must not
        survive -- that is how one document's layout leaks into another's."""
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'x': 10}, 'not_a_field': {'x': 10}}})
        assert set(out['fields']) == set(FIELD_KEYS)

    def test_an_unlisted_font_falls_back_to_the_default(self, api):
        sanitize, _, _ = api
        out = sanitize({'page': {'fontFamily': 'Comic Sans MS; DROP TABLE'}})
        assert out['page']['fontFamily'] in base.ALLOWED_FONTS

    def test_an_unlisted_paper_falls_back(self, api):
        sanitize, _, _ = api
        assert sanitize({'paper': 'A0'})['paper'] in base.ALLOWED_PAPERS

    @pytest.mark.parametrize('bad', [-5000, 99999, 'x', None])
    def test_an_out_of_range_coordinate_is_clamped_or_defaulted(self, api, bad):
        sanitize, _, _ = api
        x = sanitize({'fields': {'doc_no': {'x': bad}}})['fields']['doc_no']['x']
        assert 0 <= x <= base.CANVAS_W

    def test_font_size_is_clamped_to_the_allowed_band(self, api):
        sanitize, _, _ = api
        big = sanitize({'fields': {'doc_no': {'fontSize': 999}}})['fields']['doc_no']['fontSize']
        assert base.FONT_MIN <= big <= base.FONT_MAX

    def test_extras_are_capped(self, api):
        sanitize, _, _ = api
        out = sanitize({'extras': [{'key': 'doc_no', 'x': 1, 'y': 1}] * (base.MAX_EXTRAS + 25)})
        assert len(out['extras']) <= base.MAX_EXTRAS


class TestForwardCompatibility:
    """The upgrade case: a layout saved before a field existed must still render
    that field at its default rather than vanishing or raising."""

    def test_a_layout_missing_a_field_gets_it_at_default(self, api):
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'x': 50, 'y': 60}}})
        assert out['fields']['doc_date'] == DEFAULT['fields']['doc_date']

    def test_an_empty_layout_returns_the_full_default(self, api):
        sanitize, _, _ = api
        assert sanitize({}) == sanitize(DEFAULT)

    def test_a_non_dict_input_does_not_raise(self, api):
        sanitize, _, _ = api
        assert sanitize(None)['paper'] in base.ALLOWED_PAPERS


class TestPersistence:

    def test_get_returns_defaults_when_unset(self, db_session, api):
        _, get_layout, _ = api
        assert get_layout(branch_id=1)['paper'] == DEFAULT['paper']

    def test_save_then_get_round_trips_per_branch(self, db_session, admin_user, api):
        """Layouts are PER BRANCH -- branch 2 must not see branch 1's layout."""
        _, get_layout, save_layout = api
        save_layout({'fields': {'doc_no': {'x': 222}}}, admin_user.username, branch_id=1)
        assert get_layout(branch_id=1)['fields']['doc_no']['x'] == 222
        assert get_layout(branch_id=2)['fields']['doc_no']['x'] == DEFAULT['fields']['doc_no']['x']

    def test_corrupt_stored_json_falls_back_to_defaults(self, db_session, api):
        """A hand-edited or truncated settings row must not 500 the print page."""
        from app.settings import AppSettings
        _, get_layout, _ = api
        AppSettings.set_setting('test_preprinted_layout:1', '{not json')
        assert get_layout(branch_id=1)['paper'] == DEFAULT['paper']

    def test_save_writes_an_audit_row(self, db_session, admin_user, api):
        from app.audit.models import AuditLog
        _, _, save_layout = api
        save_layout({'paper': 'letter'}, admin_user.username, branch_id=1)
        assert AuditLog.query.filter_by(record_identifier='test_preprinted_layout').count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_preprinted_base.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.common.preprinted_base'`.

- [ ] **Step 3: Write the base**

Create `app/common/preprinted_base.py`. Lift the shared constants and helpers from
`app/sales_orders/preprinted_layout.py` **verbatim** — `CANVAS_W/H`, `SAFE_MARGIN`, the font/width/
row bounds, `FONT_GROUPS`, `ALLOWED_FONTS`, `ALLOWED_PAPERS`, `PAPER_SIZES`, `PAPER_LABELS`,
`DATE_FORMATS`, `ALLOWED_DATE_FORMATS`, `MAX_EXTRAS`, `TEXT_KEYS`, `TEXT_LABELS`, `TEXT_MAXLEN`, and
the `_clamp` / `_clean_box` / `_clean_columns` / `_clean_extras` helpers — then wrap the three public
functions in a factory:

```python
def build_layout_api(setting_key, field_keys, default_layout, audit_module, audit_identifier):
    """Return (sanitize_layout, get_layout, save_layout) bound to one document type.

    Everything these three do is identical across documents EXCEPT the setting
    key, the field list and the defaults -- which is why the eight existing
    per-module copies differ by only ~76 lines once their document names are
    normalised. A module declares its own identity and inherits the rest.
    """
```

`sanitize_layout` builds over `default_layout` using `field_keys`; `_layout_key` scopes by branch
(`f'{setting_key}:{branch_id}'`, bare key when `branch_id is None`); `save_layout` sanitises,
persists via `AppSettings.set_setting`, calls `log_audit(module=audit_module, action='update',
record_identifier=audit_identifier, ...)`, and returns the clean layout.

**Reuse the existing signatory sanitiser — do not reimplement it.** `app/common/preprinted_texts.py`
already exists and the eight current layouts all call it:
`from app.common.preprinted_texts import clean_texts`, used as
`clean_texts(raw.get('texts'), default_layout['texts'])` (see
`app/sales_orders/preprinted_layout.py:14` and `:244`). The base imports and calls it the same way;
`TEXT_KEYS` / `TEXT_LABELS` / `TEXT_MAXLEN` move into the base only as the shared constants.

Do NOT import from any existing module's `preprinted_layout.py` — the base must stand alone so those
eight stay untouched and independently changeable.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_preprinted_base.py -q --no-cov`
Expected: PASS, 15 passed.

- [ ] **Step 5: Prove the eight existing layouts are untouched**

```bash
git -C C:/envs/erp-workspace/projects/wt-p2p-preprinted status --short
```

Expected: no `app/sales_orders/`, `app/sales_invoices/`, `app/accounts_payable/`,
`app/cash_disbursements/`, `app/cash_receipts/`, `app/journal_entries/`, `app/delivery_receipts/`
or `app/payroll/` paths listed. If any appears, revert it.

- [ ] **Step 6: Commit**

```bash
git add app/common/preprinted_base.py tests/unit/test_preprinted_base.py
git commit -m "feat(print): shared pre-printed layout base"
```

---

### Task 3: The Purchase Order layout declaration

**Files:**
- Create: `app/purchase_orders/preprinted_layout.py`
- Test: `tests/unit/test_po_preprinted_layout.py`

**Interfaces:**
- Consumes: `build_layout_api` and the constants from Task 2.
- Produces: `LAYOUT_SETTING_KEY = 'po_preprinted_layout'`, `FIELD_KEYS`, `FIELD_LABELS`,
  `COLUMN_KEYS`, `COLUMN_LABELS`, `DEFAULT_PO_PREPRINTED_LAYOUT`, and the three functions from the
  factory.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_po_preprinted_layout.py`:

```python
"""The PO layout declares its own identity and inherits behaviour from the base."""
import pytest

from app.purchase_orders import preprinted_layout as pl

pytestmark = [pytest.mark.unit]


def test_it_declares_the_po_setting_key():
    assert pl.LAYOUT_SETTING_KEY == 'po_preprinted_layout'


def test_it_declares_every_po_header_field():
    assert pl.FIELD_KEYS == [
        'po_no', 'order_date', 'expected_date', 'vendor_name', 'vendor_tin',
        'vendor_address', 'payment_terms', 'reference', 'vat_treatment', 'total_amount',
    ]


def test_every_field_has_a_label_and_a_default_box():
    for k in pl.FIELD_KEYS:
        assert k in pl.FIELD_LABELS, f'{k} has no label'
        assert k in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'], f'{k} has no default box'


def test_it_declares_the_po_line_columns():
    assert pl.COLUMN_KEYS == [
        'line_number', 'product', 'description', 'quantity', 'uom', 'unit_price', 'amount',
    ]
    for k in pl.COLUMN_KEYS:
        assert k in pl.COLUMN_LABELS, f'{k} has no label'


def test_a_foreign_field_is_rejected_by_the_inherited_sanitiser():
    """Control: PO must not accept a Sales Order field. This is what stops one
    document's stored layout leaking into another's."""
    out = pl.sanitize_layout({'fields': {'customer_name': {'x': 10, 'y': 10}}})
    assert 'customer_name' not in out['fields']
    assert set(out['fields']) == set(pl.FIELD_KEYS)


def test_defaults_place_every_field_inside_the_canvas():
    from app.common import preprinted_base as base
    for k, box in pl.DEFAULT_PO_PREPRINTED_LAYOUT['fields'].items():
        assert 0 <= box['x'] <= base.CANVAS_W, k
        assert 0 <= box['y'] <= base.CANVAS_H, k
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_po_preprinted_layout.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.purchase_orders.preprinted_layout'`.

- [ ] **Step 3: Write the declaration**

Create `app/purchase_orders/preprinted_layout.py` — roughly 60 lines, no logic:

```python
"""Layout declaration for the Purchase Order pre-printed print designer.

Only this document's identity lives here: its setting key, its fields, its line
columns, and where they sit by default. All behaviour -- canvas bounds, font
allow-list, clamping, sanitisation, per-branch persistence and auditing -- comes
from app.common.preprinted_base, so this file is a declaration rather than a
ninth copy of a 275-line module.
"""
from app.common.preprinted_base import (
    CANVAS_W, CANVAS_H, ALLOWED_FONTS, TEXT_KEYS, build_layout_api)

LAYOUT_SETTING_KEY = 'po_preprinted_layout'

FIELD_KEYS = [
    'po_no', 'order_date', 'expected_date', 'vendor_name', 'vendor_tin',
    'vendor_address', 'payment_terms', 'reference', 'vat_treatment', 'total_amount',
]

FIELD_LABELS = {
    'po_no': 'PO No.',
    'order_date': 'Order Date',
    'expected_date': 'Expected Date',
    'vendor_name': 'Vendor',
    'vendor_tin': 'TIN',
    'vendor_address': 'Address',
    'payment_terms': 'Terms',
    'reference': 'Reference',
    'vat_treatment': 'VAT Treatment',
    'total_amount': 'Total Amount',
}

COLUMN_KEYS = ['line_number', 'product', 'description', 'quantity', 'uom',
               'unit_price', 'amount']

COLUMN_LABELS = {
    'line_number': '#',
    'product': 'Product',
    'description': 'Description',
    'quantity': 'Qty',
    'uom': 'UOM',
    'unit_price': 'Unit Price',
    'amount': 'Amount',          # bare 'Amount' -- this app prints no currency symbol here
}
```

Then build `DEFAULT_PO_PREPRINTED_LAYOUT` in the same shape as
`DEFAULT_SO_PREPRINTED_LAYOUT` in `app/sales_orders/preprinted_layout.py` — copy that structure and
adjust the field keys and their x/y to match the approved mockup from Task 1. Finish with:

```python
sanitize_layout, get_layout, save_layout = build_layout_api(
    LAYOUT_SETTING_KEY, FIELD_KEYS, DEFAULT_PO_PREPRINTED_LAYOUT,
    audit_module='purchase_orders', audit_identifier=LAYOUT_SETTING_KEY)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_po_preprinted_layout.py tests/unit/test_preprinted_base.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/purchase_orders/preprinted_layout.py tests/unit/test_po_preprinted_layout.py
git commit -m "feat(po): pre-printed layout declaration"
```

---

### Task 4: The Purchase Requisition and Receiving Report declarations

**Files:**
- Create: `app/purchase_requests/preprinted_layout.py`, `app/receiving_reports/preprinted_layout.py`
- Test: `tests/unit/test_pr_rr_preprinted_layout.py`

**Interfaces:**
- Consumes: `build_layout_api` from Task 2; the shape established by Task 3.
- Produces: `pr_preprinted_layout` and `rr_preprinted_layout` setting keys plus their field/column
  declarations and factory-built functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_pr_rr_preprinted_layout.py`:

```python
"""PR and RR layout declarations.

Two document-shape facts are pinned here because they are easy to get wrong by
copying PO:
  * a requisition carries NO money -- PurchaseRequestItem has no price column
  * an RR line stores only line_number / product / received_quantity; its
    description, ordered qty and UoM come from the PO line it receives
"""
import pytest

from app.purchase_requests import preprinted_layout as pr_pl
from app.receiving_reports import preprinted_layout as rr_pl

pytestmark = [pytest.mark.unit]


class TestPurchaseRequisition:

    def test_setting_key(self):
        assert pr_pl.LAYOUT_SETTING_KEY == 'pr_preprinted_layout'

    def test_fields(self):
        assert pr_pl.FIELD_KEYS == ['pr_number', 'request_date', 'date_needed', 'reason', 'branch']

    def test_columns_carry_no_money(self):
        """A requisition asks for goods, not spend -- pricing arrives at PO."""
        assert pr_pl.COLUMN_KEYS == ['line_number', 'product', 'description', 'quantity', 'uom']
        for money in ('unit_price', 'amount', 'total'):
            assert money not in pr_pl.COLUMN_KEYS
            assert money not in pr_pl.FIELD_KEYS

    def test_every_field_and_column_has_a_label(self):
        for k in pr_pl.FIELD_KEYS:
            assert k in pr_pl.FIELD_LABELS
        for k in pr_pl.COLUMN_KEYS:
            assert k in pr_pl.COLUMN_LABELS


class TestReceivingReport:

    def test_setting_key(self):
        assert rr_pl.LAYOUT_SETTING_KEY == 'rr_preprinted_layout'

    def test_fields(self):
        assert rr_pl.FIELD_KEYS == ['rr_number', 'receipt_date', 'vendor_name',
                                    'po_number', 'remarks']

    def test_columns(self):
        assert rr_pl.COLUMN_KEYS == ['line_number', 'product', 'description',
                                     'ordered_qty', 'received_quantity', 'uom']

    def test_every_field_and_column_has_a_label(self):
        for k in rr_pl.FIELD_KEYS:
            assert k in rr_pl.FIELD_LABELS
        for k in rr_pl.COLUMN_KEYS:
            assert k in rr_pl.COLUMN_LABELS


class TestTheyDoNotShareIdentity:
    """Control: three declarations built from one factory must stay distinct."""

    def test_keys_differ(self):
        from app.purchase_orders import preprinted_layout as po_pl
        keys = {pr_pl.LAYOUT_SETTING_KEY, rr_pl.LAYOUT_SETTING_KEY, po_pl.LAYOUT_SETTING_KEY}
        assert len(keys) == 3

    def test_a_po_field_is_rejected_by_the_pr_sanitiser(self):
        out = pr_pl.sanitize_layout({'fields': {'vendor_name': {'x': 10, 'y': 10}}})
        assert 'vendor_name' not in out['fields']
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_pr_rr_preprinted_layout.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError` for `app.purchase_requests.preprinted_layout`.

- [ ] **Step 3: Write both declarations**

Mirror Task 3's structure exactly. PR uses `audit_module='purchase_requests'`, RR uses
`audit_module='receiving_reports'`.

Labels:

```python
# purchase_requests
FIELD_LABELS = {'pr_number': 'PR No.', 'request_date': 'Request Date',
                'date_needed': 'Date Needed', 'reason': 'Note', 'branch': 'Branch'}
COLUMN_LABELS = {'line_number': '#', 'product': 'Product', 'description': 'Description',
                 'quantity': 'Qty', 'uom': 'UOM'}

# receiving_reports
FIELD_LABELS = {'rr_number': 'RR No.', 'receipt_date': 'Receipt Date',
                'vendor_name': 'Vendor', 'po_number': 'PO No.', 'remarks': 'Remarks'}
COLUMN_LABELS = {'line_number': '#', 'product': 'Product', 'description': 'Description',
                 'ordered_qty': 'Ordered', 'received_quantity': 'Received', 'uom': 'UOM'}
```

`'reason': 'Note'` is deliberate — commit `7d1e3d9b` renamed that label on the requisition; the
printed form must use the same word the rest of the module does.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_pr_rr_preprinted_layout.py -q --no-cov`
Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/purchase_requests/preprinted_layout.py app/receiving_reports/preprinted_layout.py \
        tests/unit/test_pr_rr_preprinted_layout.py
git commit -m "feat(pr,rr): pre-printed layout declarations"
```

---

### Task 5: The shared designer JS and CSS

**Files:**
- Create: `app/static/js/preprinted_designer.js`, `app/static/css/preprinted_designer.css`

**Interfaces:**
- Consumes: nothing (browser-side).
- Produces: a global `initPreprintedDesigner(config)` where `config` is
  `{saveUrl, fieldLabels, columnLabels, canEdit}`.

- [ ] **Step 1: Build the shared core**

`app/static/js/so_preprinted_designer.js` (431 lines) and `sv_preprinted_designer.js` differ by
**19 lines** once their document prefixes are normalised. Create
`app/static/js/preprinted_designer.js` from `so_preprinted_designer.js`, replacing every
document-specific reference with a value read from a `config` object:

```javascript
// One designer for every document type. The eight per-document copies this
// replaces differed by ~19 lines each -- the save URL and some element ids.
// Everything else (drag, clamp, snap, font/paper/date controls, save) is shared.
function initPreprintedDesigner(config) {
  // config: { saveUrl, fieldLabels, columnLabels, canEdit }
```

Copy `app/static/css/so_preprinted_designer.css` (15 lines) to
`app/static/css/preprinted_designer.css` unchanged.

**Do not delete or edit the eight existing designer JS/CSS files.**

- [ ] **Step 2: Verify it parses**

Run: `node --check app/static/js/preprinted_designer.js`
Expected: no output (exit 0). `node` is required, never skipped — a designer that does not parse
takes the whole print page down and no pytest test would see it.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/preprinted_designer.js app/static/css/preprinted_designer.css
git commit -m "feat(print): shared pre-printed designer JS and CSS"
```

---

### Task 6: Wire Purchase Order — template, routes, settings

**Files:**
- Create: `app/purchase_orders/templates/purchase_orders/print_preprinted.html`
- Modify: `app/purchase_orders/views.py` (print route + layout save route)
- Modify: `app/purchase_orders/models.py` (`VAT_TREATMENT_LABELS` + the `vat_treatment_label`
  property — derived only; no column, no migration)
- Test: `tests/integration/test_p2p_preprinted_print.py`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces: `GET /purchase-orders/<id>/print` honouring `po_print_form`;
  `POST /purchase-orders/print-layout`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_p2p_preprinted_print.py` covering PO first (PR/RR are added in
Task 7). Model the fixtures on `tests/integration/test_purchase_orders_*.py`'s existing setup.

```python
"""Pre-printed print routing and gating for the P2P documents.

Asserted on the RENDERED GET, never by posting a payload the test built itself:
a POST-contract test structurally cannot see a template that failed to render a
field (this is how BUG-DR-EDIT-FALSE-CONFLICT shipped green in this codebase).
"""
import pytest

from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


class TestPurchaseOrderPrintForm:

    def test_current_renders_the_standard_form(self, client, db_session, admin_user,
                                               branch_manila, approved_po):
        AppSettings.set_setting('po_print_form', 'current')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        assert b'pp-canvas' not in resp.data, 'rendered the pre-printed overlay instead'

    def test_preprinted_renders_the_overlay_with_every_declared_field(
            self, client, db_session, admin_user, branch_manila, approved_po):
        from app.purchase_orders.preprinted_layout import FIELD_KEYS
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'pp-canvas' in body
        for key in FIELD_KEYS:
            assert f'data-el="{key}"' in body, f'{key} is not rendered on the overlay'

    @pytest.mark.parametrize('stored,printed', [
        ('inclusive', 'VAT Inclusive'),
        ('exclusive', 'VAT Exclusive'),
        ('zero_rated', 'Zero-Rated'),
    ])
    def test_vat_treatment_prints_its_human_label_not_the_stored_token(
            self, client, db_session, admin_user, branch_manila, approved_po,
            stored, printed):
        """`vat_treatment` is stored as a token ('zero_rated'), which is not
        something a supplier should read off a printed order. The overlay must
        print the same wording PurchaseOrderForm's own SelectField shows --
        form, detail and print must share the document's jargon.

        All three values are exercised on purpose: one case alone would also
        pass against a template that hardcoded that one label.
        """
        import re
        approved_po.vat_treatment = stored
        AppSettings.set_setting('po_print_form', 'preprinted')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}/print').data.decode()
        cell = re.search(r'data-el="vat_treatment"[^>]*>([^<]*)<', body)
        assert cell, 'the vat_treatment box is not rendered on the overlay'
        assert cell.group(1).strip() == printed

    def test_hidden_refuses_and_redirects(self, client, db_session, admin_user,
                                          branch_manila, approved_po):
        AppSettings.set_setting('po_print_form', 'hidden')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{approved_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data


class TestPrintAccessGate:
    """po_print_access defaults to approved_only: a DRAFT purchase order must not
    be printable, because a draft PO sent to a supplier is a commercial problem.
    Tested in BOTH directions, and at the ROUTE -- a hidden button is not access
    control."""

    def test_a_draft_is_refused_at_the_route(self, client, db_session, admin_user,
                                             branch_manila, draft_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        resp = client.get(f'/purchase-orders/{draft_po.id}/print', follow_redirects=True)
        assert b'pp-canvas' not in resp.data
        assert b'<table' not in resp.data or b'not enabled' in resp.data

    def test_an_approved_po_is_allowed(self, client, db_session, admin_user,
                                       branch_manila, approved_po):
        """The control. Without it the gate could refuse everything and the test
        above would still pass."""
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        assert client.get(f'/purchase-orders/{approved_po.id}/print').status_code == 200

    def test_the_print_button_is_hidden_on_a_draft_detail_page(
            self, client, db_session, admin_user, branch_manila, draft_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{draft_po.id}').data.decode()
        assert f'/purchase-orders/{draft_po.id}/print' not in body

    def test_the_print_button_is_shown_on_an_approved_detail_page(
            self, client, db_session, admin_user, branch_manila, approved_po):
        AppSettings.set_setting('po_print_access', 'approved_only')
        db_session.commit()
        _login(client, admin_user, branch_manila)
        body = client.get(f'/purchase-orders/{approved_po.id}').data.decode()
        assert f'/purchase-orders/{approved_po.id}/print' in body


class TestLayoutSave:

    def test_full_access_can_save(self, client, db_session, admin_user, branch_manila):
        _login(client, admin_user, branch_manila)
        resp = client.post('/purchase-orders/print-layout', json={'paper': 'letter'})
        assert resp.status_code == 200
        assert resp.get_json()['layout']['paper'] == 'letter'

    def test_a_staff_user_is_refused(self, client, db_session, staff_user, branch_manila):
        """Layout edits change what prints on a client's real stationery."""
        _login(client, staff_user, branch_manila)
        assert client.post('/purchase-orders/print-layout', json={}).status_code == 403
```

**Implementer note — the fixtures are NOT importable as-is.** `draft_po` and `approved_po` exist in
`tests/integration/test_po_amend_ui.py` (lines 94 and 99, built by its `_make_draft_po` helper at
line 78) and again in `test_po_amend.py`, but they are **module-local fixtures, not in
`tests/conftest.py`**, so a new test module cannot simply request them.

Copy `_make_draft_po` and both fixtures into your new test module. Note they are built on the
**`branch_manila`** fixture, NOT `main_branch` — so use `branch_manila` consistently in this file,
including in `_login(client, admin_user, branch_manila)`, or the PO will not be visible in the
session branch and every route will 404. Do not "fix" that by moving the fixtures to conftest; that widens the
change into files this task does not own.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_p2p_preprinted_print.py -q --no-cov`
Expected: FAIL — the overlay template does not exist and `po_print_form` is not read.

- [ ] **Step 3: Create the overlay template**

Copy `app/sales_orders/templates/sales_orders/print_preprinted.html` (157 lines) to
`app/purchase_orders/templates/purchase_orders/print_preprinted.html` and adapt it: swap `so` for
`po`, use the PO field/column keys, and load the SHARED assets with a cache-buster:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/preprinted_designer.css') }}?v=1">
<script src="{{ url_for('static', filename='js/preprinted_designer.js') }}?v=1"></script>
<script>
  initPreprintedDesigner({
    saveUrl: '{{ url_for("purchase_orders.save_print_layout") }}',
    fieldLabels: {{ field_labels | tojson }},
    columnLabels: {{ col_labels | tojson }},
    canEdit: {{ can_edit_layout | tojson }}
  });
</script>
```

Match the approved Task 1 mockup for placement and chrome.

**`vat_treatment` prints a label, never the stored token.** The column holds `inclusive` /
`exclusive` / `zero_rated`; printing that raw puts a database token on a supplier-facing document.
Add the map and a derived read-only property to `app/purchase_orders/models.py`, beside the
existing `VAT_TREATMENTS` tuple at line 16 (no column, no migration — this is derived state):

```python
VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')

# The wording PurchaseOrderForm's SelectField shows (app/purchase_orders/forms.py:25).
# Form, detail and print must share the document's jargon, so the labels live in ONE
# place rather than being re-spelled per template.
VAT_TREATMENT_LABELS = {
    'inclusive': 'VAT Inclusive',
    'exclusive': 'VAT Exclusive',
    'zero_rated': 'Zero-Rated',
}
```

and on `PurchaseOrder`:

```python
    @property
    def vat_treatment_label(self):
        """Human wording for the stored token. Falls back to the raw value so an
        unrecognised token is visible on the page rather than printing blank."""
        return VAT_TREATMENT_LABELS.get(self.vat_treatment, self.vat_treatment)
```

The overlay then renders `{{ po.vat_treatment_label }}`, not `{{ po.vat_treatment }}`.

**Scope note:** `purchase_orders/detail.html:36` prints the raw token today
(`<strong>VAT Treatment:</strong> {{ po.vat_treatment }}`). That is the DETAIL surface, which this
arc does not own — leave it alone. The property added here is what that sub-project will use when
it lands; do not widen this task to fix it.

- [ ] **Step 4: Wire the routes**

In `app/purchase_orders/views.py`, mirror `app/sales_orders/views.py:894` `print_so` and `:965`
`save_print_layout` exactly, substituting the PO model, template and layout module — and add the
access gate:

```python
    po_print_form = AppSettings.get_setting('po_print_form', 'current')
    if po_print_form == 'hidden':
        flash('Purchase Order printing is not enabled.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    # A DRAFT purchase order must not reach a supplier. Enforced HERE, not only by
    # hiding the button -- a direct GET bypasses the template entirely.
    if AppSettings.get_setting('po_print_access', 'approved_only') == 'approved_only' \
            and po.status == 'draft':
        flash('A draft Purchase Order cannot be printed. Approve it first.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
```

Then gate the Print button in `app/purchase_orders/templates/purchase_orders/detail.html` on the
same condition, using a Jinja `{# #}` comment if one is needed near it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_p2p_preprinted_print.py -q --no-cov`
Expected: PASS, 9 passed.

- [ ] **Step 6: Mutation-check the gate**

Temporarily delete the `po_print_access` block from the view (leaving the template gate in place).
Run the same command. Expected: FAIL on `test_a_draft_is_refused_at_the_route` — proving the test
attacks the ROUTE and not merely the button. Restore it.

- [ ] **Step 7: Commit**

```bash
git add app/purchase_orders/ tests/integration/test_p2p_preprinted_print.py
git commit -m "feat(po): pre-printed print form, designer wiring and print gate"
```

---

### Task 7: Wire Purchase Requisition and Receiving Report

**Files:**
- Create: `app/purchase_requests/templates/purchase_requests/print_preprinted.html`,
  `app/receiving_reports/templates/receiving_reports/print_preprinted.html`
- Modify: `app/purchase_requests/views.py`, `app/receiving_reports/views.py`
- Test: `tests/integration/test_p2p_preprinted_print.py` (extend)

**Interfaces:**
- Consumes: Tasks 2-6.
- Produces: `pr_print_form` / `rr_print_form` routing and both layout-save routes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_p2p_preprinted_print.py` a class per module mirroring
`TestPurchaseOrderPrintForm` — `current` renders the standard form, `preprinted` renders the overlay
with every declared field present as `data-el="<key>"`, `hidden` refuses.

**There is no `approved_rr` fixture — build one.** The RR suites use module-local helpers, not
fixtures: `_make_draft_rr(db_session, branch, po, received, number=...)` in
`tests/integration/test_receiving_reports_lifecycle.py:39` and `_draft_rr(...)` in
`test_receiving_report_stock_posting.py:48`. Copy one of those helpers into your test module,
approve the RR through its own route, and use `branch_manila` to match the PO fixtures above — an RR
must reference a PO, so both have to live in the same branch.

Add one control per module:

```python
def test_the_rr_overlay_derives_its_line_columns_from_the_po_line(
        self, client, db_session, admin_user, branch_manila, approved_rr):
    """ReceivingReportItem stores only line_number / product / received_quantity.
    description, ordered_qty and uom come from purchase_order_item -- if the
    template expects columns on the RR line itself they render empty."""
    AppSettings.set_setting('rr_print_form', 'preprinted')
    db_session.commit()
    _login(client, admin_user, branch_manila)
    body = client.get(f'/receiving-reports/{approved_rr.id}/print').data.decode()
    assert 'data-col="ordered_qty"' in body
    assert 'data-col="uom"' in body
```

**No print-access gate for PR or RR** — they are internal documents; `*_print_form: hidden` is
their off switch. Do not add one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_p2p_preprinted_print.py -q --no-cov`
Expected: FAIL on the new PR/RR classes only; the PO classes stay green.

- [ ] **Step 3: Create both templates and wire both routes**

Mirror Task 6 exactly for each module. Both `print_preprinted.html` files load the same shared
`preprinted_designer.js`/`.css` with `?v=1`.

For RR, resolve the derived columns through the relationship rather than the line:

```jinja
{% set po_line = li.purchase_order_item %}
<div class="pp-col" data-col="ordered_qty">{{ po_line.quantity if po_line else '' }}</div>
<div class="pp-col" data-col="uom">{{ po_line.uom_text or (po_line.unit_of_measure.code if po_line and po_line.unit_of_measure else '') }}</div>
```

For PR, render `date_needed` as **ASAP** when the flag is set:

```jinja
<div class="pp-el" data-el="date_needed">{{ 'ASAP' if pr.date_needed_asap else (pr.date_needed.strftime('%Y-%m-%d') if pr.date_needed else '') }}</div>
```

The model stores those as mutually exclusive; never print both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_p2p_preprinted_print.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Run the three modules' full suites**

```bash
venv/Scripts/python.exe -m pytest tests/integration/test_pr_*.py tests/integration/test_purchase_request*.py \
  tests/integration/test_po_*.py tests/integration/test_purchase_orders_*.py \
  tests/integration/test_receiving_report*.py tests/integration/test_receiving_reports_*.py \
  tests/unit/test_preprinted_base.py tests/unit/test_po_preprinted_layout.py \
  tests/unit/test_pr_rr_preprinted_layout.py -q --no-cov
```

Expected: PASS with no failures.

- [ ] **Step 6: Commit**

```bash
git add app/purchase_requests/ app/receiving_reports/ tests/integration/test_p2p_preprinted_print.py
git commit -m "feat(pr,rr): pre-printed print form and designer wiring"
```

---

### Task 8: Browser pass (BLOCKING)

**Files:** none — verification only.

- [ ] **Step 1: Provision from the branch**

```
/ui-test philgen --branch feat/p2p-preprinted-designer
```

philgen has real purchase requisitions and orders. If a receiving report does not exist in that
data, create one through the UI rather than seeding.

- [ ] **Step 2: Drive each of the three documents**

For PR, PO and RR in turn:

1. Set the module's `*_print_form` to `preprinted` in Company Settings.
2. Open a document's Print view. The overlay canvas renders, every declared field appears, and the
   line band shows the document's real lines.
3. As an admin, drag a field, change the font and the paper size, and Save. Reload the page and
   confirm the layout persisted.
4. Switch `*_print_form` back to `current` and confirm the standard form returns.

Then, for PO only: set `po_print_access` to `approved_only`, open a DRAFT purchase order, and
confirm **the Print button is absent** and a direct GET of `/purchase-orders/<id>/print` is refused.

- [ ] **Step 3: Confirm the eight existing documents still print**

Open one Sales Order and one AP voucher print view. Both must be unchanged. This is the check that
the shared base did not leak into the untouched modules.

- [ ] **Step 4: Record the pass**

```powershell
$sha = (git -C <worktree> rev-parse feat/p2p-preprinted-designer).Trim()
& <project-python> -c "import sys; sys.path.insert(0, r'C:\envs\erp-workspace\.claude\skills\_lib'); import ui_pass; ui_pass.record(r'C:\envs\erp-workspace\projects\cas', '$sha', 'feat/p2p-preprinted-designer', '<YYYY-MM-DD>')"
```

**If the Chrome extension is disconnected, STOP and ask.** This branch is almost entirely templates
and JS; it may not merge on pytest-only evidence.

---

## Follow-up plan (not this one)

Styling parity, to be planned separately once this merges: a branded `print.html` for PO and RR
mirroring PR's existing 283-line template, `list_print.html` for all three, and extraction of PR's
letterhead + signatory-editor markup into a shared partial that PR itself then uses.
