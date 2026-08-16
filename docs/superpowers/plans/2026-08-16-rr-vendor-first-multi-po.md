# Receiving Report — vendor-first, multi-PO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Receiving Report is created vendor-first and can receive lines from several of that vendor's purchase orders in one document.

**Architecture:** The PO link already lives on the line (`ReceivingReportItem.purchase_order_item_id`, `nullable=False`). This plan makes that the *only* link: every consumer is rewritten to derive the PO(s) from the lines **while the header column still exists** (branch stays green), and only then is `receiving_reports.purchase_order_id` dropped. `vendor_id` becomes the header key.

**Tech Stack:** Flask 3, SQLAlchemy 2.0, SQLite, WTForms, Jinja, Choices.js, hand-written Alembic batch migrations, pytest.

**Design spec:** `docs/superpowers/specs/2026-08-16-rr-vendor-first-multi-po-design.md` — read it before Task 1.

## Global Constraints

- **The backref from a PO line to its order is `poi.order`, NOT `poi.purchase_order`** (`PurchaseOrder.line_items = db.relationship('PurchaseOrderItem', backref='order')`, `app/purchase_orders/models.py:107`). An earlier draft of this plan used the wrong name in two places; Task 1's implementer caught it via TDD RED. Do not reintroduce it.

- Work in a worktree cut from the INNER repo: `git -C projects/cas worktree add ../wt-rr-multipo -b feat/rr-vendor-first main`. Never commit to `main`. Copy `.env` into the worktree.
- Python is `C:/envs/erp-workspace/projects/cas/venv/Scripts/python.exe` (absolute — a worktree has no venv). Git: always `git -C <worktree> …`; the shell cwd persists between calls.
- **Never state an expected pass count in a step.** Confirm zero failures instead. Parametrised tests make any fixed number wrong, and a stated number invites adding or deleting tests to reach it.
- SQLAlchemy 2.0 spellings only: `db.session.get(Model, id)` / `db.get_or_404(Model, id)`. Never `Model.query.get(...)`. The suite is at zero warnings.
- Jinja `{# #}` comments near gated markup, never `<!-- -->` — HTML comments are served and defeat absence assertions. Positive assertions have the same trap: never assert a literal that also appears in inline `<style>`/`<script>`; sweep those blocks before choosing an assertion string.
- No JS `confirm()`/`alert()`/`prompt()`. Peso sign is the literal `₱`, never `&#8369;`.
- Mutation-prove every new test: apply the mutation it targets, observe RED, revert, verify the restore with a **sha256 hash, not `git status`** — this repo has mixed line endings per file and a text-mode rewrite silently normalises them, which `git diff` hides under `core.autocrlf=true`.
- Select mutation-verification runs by **path or node id, never `-k`** — a `-k` filter that collects none of the relevant tests reports a false GREEN.
- Stage explicit file paths. **Never `git add <directory>`.**
- `app/receiving_reports/*`, `app/purchase_billing.py` and `app/purchase_orders/models.py` are `regression-map.json` keys. Run the mapped dependents **by marker** (`receiving_reports` selects 218, `purchase_orders` 337, `purchase_requests` 471 since 2026-08-16) **and** the changed files by explicit path.
- Any file this branch creates that more than one module imports must be added to `regression-map.json` in the **same commit**.

---

### Task 1: Derive the PO(s) from the lines, and move every reader onto it

The column still exists after this task. Nothing reads it. That is what makes Task 6's drop safe.

**Files:**
- Modify: `app/receiving_reports/models.py`
- Modify: `app/purchase_billing.py:118-126`
- Modify: `app/receiving_reports/templates/receiving_reports/detail.html:29`, `list.html:80`, `print.html:30`
- Test: `tests/unit/test_receiving_report_model.py`, `tests/integration/test_rr_po_derivation.py` (create)

**Interfaces:**
- Produces on `ReceivingReport`: `purchase_orders` → `list[PurchaseOrder]`, distinct, ordered by `po_number`; `po_number_display` → `str` (the number when exactly one, `''` when none, `'{n} POs'` when several).

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_rr_po_derivation.py
"""The PO(s) an RR touches are derived from its lines, not from a header column.

The header FK still exists at this task; these tests must pass WITHOUT reading it,
which is what lets Task 6 drop it.
"""
import pytest
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


class TestDerivation:

    def test_one_po_reports_that_po(self, db_session, rr_one_po):
        assert [po.po_number for po in rr_one_po.purchase_orders] == ['PO-A']
        assert rr_one_po.po_number_display == 'PO-A'

    def test_two_pos_are_both_listed_and_deduped(self, db_session, rr_two_pos):
        assert [po.po_number for po in rr_two_pos.purchase_orders] == ['PO-A', 'PO-B']
        assert rr_two_pos.po_number_display == '2 POs'

    def test_two_lines_from_ONE_po_report_that_po_once(self, db_session, rr_two_lines_one_po):
        """Control: dedupe must not collapse to 'many' just because there are 2 lines."""
        assert [po.po_number for po in rr_two_lines_one_po.purchase_orders] == ['PO-A']
        assert rr_two_lines_one_po.po_number_display == 'PO-A'

    def test_derivation_does_not_read_the_header_column(self, db_session, rr_two_pos):
        """Mutation anchor: blanking the header FK must change nothing."""
        rr_two_pos.purchase_order_id = None
        db.session.flush()
        assert len(rr_two_pos.purchase_orders) == 2
```

Build the three fixtures in this module from the existing helpers in
`tests/integration/test_receiving_reports_lifecycle.py` (`_make_draft_rr` at its line 39) — they are
module-local, so copy what you need rather than importing across test modules.

- [ ] **Step 2: Run them and watch them fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_rr_po_derivation.py -q --no-cov`
Expected: FAIL — `AttributeError: 'ReceivingReport' object has no attribute 'purchase_orders'`.

- [ ] **Step 3: Add the derivation to the model**

```python
    @property
    def purchase_orders(self):
        """Distinct POs this receipt draws on, ordered by number.

        Derived from the lines, never from a header column: one receipt may
        settle several of a vendor's orders, so no single header FK can be true.
        `purchase_order_item_id` is nullable=False, so every line has one.
        """
        seen, out = set(), []
        for li in self.line_items:
            poi = li.purchase_order_item
            po = poi.order if poi else None
            if po is not None and po.id not in seen:
                seen.add(po.id)
                out.append(po)
        return sorted(out, key=lambda p: (p.po_number or ''))

    @property
    def po_number_display(self):
        """What a list column shows: the number when unambiguous, else a count."""
        pos = self.purchase_orders
        if not pos:
            return ''
        return pos[0].po_number if len(pos) == 1 else f'{len(pos)} POs'
```

- [ ] **Step 4: Rewrite the readers**

`app/purchase_billing.py` — replace the header-column filter. This is the one that is not cosmetic:
it decides whether a PO is billed directly or through its RR, so a stale filter makes a received PO
look unreceived and billable **twice**.

```python
        has_rr = (db.session.query(ReceivingReport.id)
                  .join(ReceivingReportItem,
                        ReceivingReportItem.receiving_report_id == ReceivingReport.id)
                  .join(PurchaseOrderItem,
                        PurchaseOrderItem.id == ReceivingReportItem.purchase_order_item_id)
                  .filter(PurchaseOrderItem.purchase_order_id == po.id,
                          ReceivingReport.status.in_(('approved', 'billed')))
                  .first())
```

Import `ReceivingReportItem` and `PurchaseOrderItem` there if they are not already imported.

Templates:
- `detail.html:29` → link each of `rr.purchase_orders`
- `list.html:80` → `{{ rr.po_number_display or '—' }}`
- `print.html:30` → drop the header `PO #:` line (Task 5 puts it on the line grid)

- [ ] **Step 5: Run the tests, then the billing suite**

```
venv/Scripts/python.exe -m pytest tests/integration/test_rr_po_derivation.py \
  tests/integration/test_ap_po_billing_picker*.py tests/integration/test_receiving_report*.py -q --no-cov
```
Expected: PASS, zero failures.

- [ ] **Step 6: Mutation-prove the billing rewrite**

Change the join's filter to `PurchaseOrderItem.purchase_order_id == 0`. Expect the AP billing-picker
tests to fail. Revert; verify the restore by sha256.

- [ ] **Step 7: Commit**

```bash
git add app/receiving_reports/models.py app/purchase_billing.py \
        app/receiving_reports/templates/receiving_reports/detail.html \
        app/receiving_reports/templates/receiving_reports/list.html \
        app/receiving_reports/templates/receiving_reports/print.html \
        tests/integration/test_rr_po_derivation.py
git commit -m "feat(rr): derive the purchase orders from the lines, not a header column"
```

---

### Task 2: One vendor per receipt, and a ceiling that sees the whole payload

**This closes a defect that exists on `main` today**, independent of the new form: `_parse_rr_lines`
appends one line per payload entry with no dedupe, and the approve guard checks per line against a
ceiling that excludes the whole RR — so two lines of 10 against an open 10 each pass. Same class as
`BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION` (fixed in PO, cas `66bf733f`).

**Files:**
- Modify: `app/receiving_reports/views.py` (`_parse_rr_lines` ~:118, the approve guard ~:360)
- Test: `tests/integration/test_rr_receipt_ceiling.py` (create)

**Interfaces:**
- Produces `assert_payload_within_open_qty(pairs, exclude_rr_id=None)` in `app/receiving_reports/views.py`, where `pairs` is an iterable of `(purchase_order_item_id, qty)`. Raises `ValueError` naming every contributing line.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_rr_receipt_ceiling.py
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


class TestTheCeilingSeesTheWholePayload:

    def test_two_lines_on_one_po_line_summing_over_open_is_refused(
            self, client, db_session, admin_user, main_branch, po_line_open_10):
        """Each line is within the ceiling alone; together they are not."""
        resp = _post_rr(client, po_line_open_10, [6, 6])
        assert b'exceeds the open quantity' in resp.data or b'between them' in resp.data
        assert ReceivingReport.query.count() == 0

    def test_exactly_at_the_ceiling_is_allowed(
            self, client, db_session, admin_user, main_branch, po_line_open_10):
        """Control. A receiver splitting one PO line across two deliveries is
        legitimate; an off-by-one that rejects the boundary is a regression."""
        resp = _post_rr(client, po_line_open_10, [4, 6])
        assert ReceivingReport.query.count() == 1

    def test_two_DIFFERENT_po_lines_each_within_their_own_ceiling_pass(
            self, client, db_session, admin_user, main_branch, two_po_lines):
        """Control. A naive 'reject duplicate PO-line ids' fix breaks this --
        which is the normal case of receiving several lines of one order."""
        assert ReceivingReport.query.count() == 1

    def test_a_line_from_another_vendor_is_refused_at_the_route(
            self, client, db_session, admin_user, main_branch, po_other_vendor):
        """A picker filter is not enforcement: a raw POST bypasses it."""
        resp = _post_rr(client, po_other_vendor, [1])
        assert ReceivingReport.query.count() == 0
```

Write `_post_rr(client, po_item, quantities)` in this module: it POSTs `/receiving-reports/create`
with `line_items` as JSON `[{"purchase_order_item_id": …, "received_quantity": …}, …]`, one entry per
quantity, all naming the same PO line unless the fixture says otherwise.

- [ ] **Step 2: Run them and watch them fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_rr_receipt_ceiling.py -q --no-cov`
Expected: the over-receipt test FAILS by creating the RR anyway — that is the bug.

- [ ] **Step 3: Implement the aggregate guard**

Sum the payload per `purchase_order_item_id` **before** building any line, then check each PO line
once. Name every contributing line in the message, as the PO fix does:

```python
def assert_payload_within_open_qty(pairs, exclude_rr_id=None):
    """Refuse a payload that receives more of a PO line than remains open.

    Checked over the WHOLE payload, not per line: the ceiling comes from the
    database, so a per-line check cannot see the siblings in its own submission
    and two lines of 10 against an open 10 would each pass.
    """
    totals, where = {}, {}
    for idx, (poi_id, qty) in enumerate(pairs, start=1):
        totals[poi_id] = totals.get(poi_id, Decimal('0')) + Decimal(str(qty or 0))
        where.setdefault(poi_id, []).append(idx)
    for poi_id, total in totals.items():
        poi = db.session.get(PurchaseOrderItem, poi_id)
        if poi is None:
            raise ValueError(f'Line {where[poi_id][0]}: that purchase order line no longer exists.')
        open_qty = po_line_open_qty(poi, exclude_rr_id=exclude_rr_id)
        if total > open_qty:
            label = (poi.product.name if poi.product else (poi.description or 'this item'))
            lines = ', '.join(str(i) for i in where[poi_id])
            raise ValueError(
                f'Line{"s" if len(where[poi_id]) > 1 else ""} {lines}: only {open_qty} of '
                f'{label} remain open, but these lines receive {total} between them.')
```

Call it from `_parse_rr_lines` **before** any `ReceivingReportItem` is appended, and from the approve
guard over `rr.line_items` with `exclude_rr_id=rr.id`. Add the one-vendor check in the same pass:
every `poi.purchase_order.vendor_id` must equal the header `vendor_id`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_rr_receipt_ceiling.py -q --no-cov`
Expected: PASS, zero failures.

- [ ] **Step 5: Mutation-prove each guard**

Three mutations, each reverted and sha256-verified: (a) check per line instead of per total — the
over-receipt test must go RED; (b) drop the vendor check — the cross-vendor test must go RED; (c)
change `>` to `>=` — the exactly-at-ceiling control must go RED.

- [ ] **Step 6: Commit**

```bash
git add app/receiving_reports/views.py tests/integration/test_rr_receipt_ceiling.py
git commit -m "fix(rr): weigh one receipt's payload against each PO line as a whole"
```

---

### Task 3: Vendor-scoped eligibility and the pull payload

**Files:**
- Modify: `app/receiving_reports/views.py` (`_eligible_purchase_orders` ~:54, `_po_lines_payload` ~:63, the create/edit views)
- Modify: `app/receiving_reports/forms.py`
- Test: `tests/integration/test_rr_vendor_scoping.py` (create)

**Interfaces:**
- Consumes Task 2's guard.
- Produces `_eligible_purchase_orders(branch_id, vendor_id)` — approved/partially-received POs of that vendor, in that branch, with at least one line still open.
- `ReceivingReportForm` gains `vendor_id = SelectField('Vendor', coerce=int, validate_choice=False, validators=[DataRequired(message='Vendor is required.')])` and **loses** `purchase_order_id`.

- [ ] **Step 1: Write the failing tests**

Cover: only the selected vendor's POs are offered; a PO of another vendor is never in the payload; a
PO with no open line is excluded; a PO in another branch is excluded (control: the same PO in the
session branch IS offered).

- [ ] **Step 2: Run them and watch them fail**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_rr_vendor_scoping.py -q --no-cov`
Expected: FAIL — `_eligible_purchase_orders()` takes 1 positional argument.

- [ ] **Step 3: Implement**

Add the `vendor_id` filter to the query; thread it from the view's form data; populate the vendor
choices from `get_active_vendors()` the way `app/purchase_orders/views.py` does. Keep the branch
filter exactly as it is.

- [ ] **Step 4: Run the tests to verify they pass**, then commit.

```bash
git add app/receiving_reports/views.py app/receiving_reports/forms.py \
        tests/integration/test_rr_vendor_scoping.py
git commit -m "feat(rr): scope receivable purchase orders to the chosen vendor"
```

---

### Task 4: The form — vendor first, pull from purchase orders

**Files:**
- Modify: `app/receiving_reports/templates/receiving_reports/form.html`
- Test: `tests/integration/test_rr_form_render.py` (create)

**Interfaces:** consumes Tasks 2-3.

- [ ] **Step 1: Write the failing render tests**

Assert on the **rendered GET**, never by posting a payload the test built itself — a POST-contract
test structurally cannot see a field the template failed to render. Assert: a `vendor_id` picker is
present; a `+ Pull from Purchase Orders` control is present; the grid has a `From PO` column header;
and the old single-PO `purchase_order_id` select is **absent** (pair that absence with a positive
assertion so it cannot pass vacuously).

- [ ] **Step 2: Run them and watch them fail**, then build the template.

Mirror `app/purchase_orders/templates/purchase_orders/form.html`: vendor Choices picker first, then
the pull modal, then the line grid. Carry over the two picker behaviours fixed on 2026-08-16 —
**re-pulling merges** into the existing row rather than stacking a duplicate, and **a pull consumes
the seeded blank row**. Changing the vendor once lines exist must not silently orphan them: block it
or clear the grid with a visible warning.

Note the PO form keeps its picker JS in a **separate `<script>` block** from the line-identity block
on purpose — `tests/integration/_line_identity_js.py` executes the latter in a minimal DOM shim and
picker code throws there. Keep the same split.

- [ ] **Step 3: Run the tests to verify they pass**, then commit.

---

### Task 5: Move `po_number` from a pre-printed header field to a line column

Free to do now and not later: `rr_preprinted_layout` shipped 2026-08-16 and has never been deployed,
so no client has a saved layout keyed on its current `FIELD_KEYS`/`COLUMN_KEYS`.

**Files:**
- Modify: `app/receiving_reports/preprinted_layout.py`
- Modify: `app/receiving_reports/templates/receiving_reports/print_preprinted.html`
- Modify: `app/receiving_reports/templates/receiving_reports/print.html` (add the same `PO No.` column to the PLAIN print's line table — Task 1 removed its header `PO #:` line, so without this the plain printout carries no PO reference at all)
- Test: `tests/unit/test_pr_rr_preprinted_layout.py`, `tests/integration/test_p2p_preprinted_print.py`

- [ ] **Step 1: Update the declaration and its tests**

`FIELD_KEYS` → `['rr_number', 'receipt_date', 'vendor_name', 'remarks']`.
`COLUMN_KEYS` → `['line_number', 'product', 'description', 'po_number', 'ordered_qty', 'received_quantity', 'uom']`, with `'po_number': 'PO No.'` in `COLUMN_LABELS`.

Give the new column a default `x`/`width` that keeps the band tiling without overlap — the existing
tests assert exactly that, so they will tell you if it does not.

- [ ] **Step 2: Render the column per line**

```jinja
<div class="pp-col" data-col="po_number">{{ li.purchase_order_item.order.po_number
    if li.purchase_order_item and li.purchase_order_item.order else '' }}</div>
```

Assert it renders the **actual PO number**, not merely that the element exists — an element that
renders empty satisfies a presence check, and empty is exactly the failure worth catching.

- [ ] **Step 3: Run the preprinted suites, then commit.**

---

### Task 6: Drop the header column

Everything stopped reading it in Task 1. Do this last among the code tasks.

**Files:**
- Create: `migrations/versions/rrmulti_0001_drop_rr_po_fk.py`
- Modify: `app/receiving_reports/models.py`
- Test: `tests/integration/test_rr_multipo_migration.py` (create)

- [ ] **Step 1: Write the migration**

Hand-written batch ops — `Migrate()` runs **without** `render_as_batch`, so autogenerate emits plain
`ALTER` statements SQLite cannot run.

```python
def upgrade():
    conn = op.get_bind()
    # 1. backfill vendor_id from the header PO before tightening it -- every
    #    existing row has exactly one PO, so this is total.
    conn.execute(sa.text("""
        UPDATE receiving_reports
           SET vendor_id = (SELECT po.vendor_id FROM purchase_orders po
                             WHERE po.id = receiving_reports.purchase_order_id)
         WHERE vendor_id IS NULL"""))
    with op.batch_alter_table('receiving_reports') as b:
        b.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        b.drop_column('purchase_order_id')
```

Write a real `downgrade()` that re-adds the column as a plain `sa.Integer` (a batch `add_column`
cannot carry an inline `sa.ForeignKey` — SQLite raises "Constraint must have a name") and repopulates
it from the first line's PO.

- [ ] **Step 2: Verify on a COPY of a real client database, not a fixture**

A conftest `create_all()` builds today's model, not the migration history, so it cannot prove a
constraint change. Copy `clients/philgen/backups/<newest>.db` to a scratch file, run
`flask db upgrade` against it, then assert: `purchase_order_id` is gone, `vendor_id` is NOT NULL and
fully populated, and every pre-existing RR still resolves its PO through its lines. Paste the output.

- [ ] **Step 3: Remove the column from the model, and retire the one test that writes it**

`tests/integration/test_rr_po_derivation.py::TestDerivation::test_derivation_does_not_read_the_header_column` sets `rr.purchase_order_id = None` as a mutation anchor. That column no longer exists after this task, so the test must be **deleted, not weakened** — its purpose (proving the readers do not consult the header column) is now guaranteed by the schema itself. Leave the other three derivation tests untouched; they are what still prove the accessor works.

- [ ] **Step 4: Run the full RR + billing surface, then commit.**

---

### Task 7: Browser gate — BLOCKING

A numbered task, not a trailing note: this is the only step that proves the plan against reality.

- [ ] **Step 1: Provision against realistic data**

`/ui-test philgen --branch feat/rr-vendor-first` — philgen has real vendors, products and POs.

- [ ] **Step 2: Drive one delivery spanning two POs of one vendor, end to end**

Pick the vendor; pull lines from **two** different POs; save; approve; then check the detail page,
the list row, the plain print and the pre-printed overlay all show both PO numbers correctly.

Also drive, in the same session:
- re-pulling the same PO line **merges** rather than stacking, and the seeded blank row is consumed;
- an over-receipt across two lines of one PO line is **refused**, with both lines named;
- after approval, that PO is **not** offered for direct billing in the AP picker, and is billable via
  the RR.

Known driver traps, all previously paid for: a Choices picker's `+ Add new …` entry opens a modal
overlay that then intercepts every later click, and a picker's placeholder carries
`data-value="0"` — filter on a `data-value` that is numeric **and non-zero**.

- [ ] **Step 3: Record the pass and tear down**

Record it for `/ship`'s UI gate, then `/ui-test philgen down`. The record is keyed on the branch tip
SHA, so any further commit invalidates it — make this the last thing before merging.

---

## Self-review

Checked against the spec:

- ★ multi-PO per vendor → Tasks 3, 4, 7. ★ drop the header FK → Tasks 1 and 6 (rewrite first, drop
  second, so the branch never goes red). ★ `po_number` field → column → Task 5.
- `purchase_billing.py` double-bill route → Task 1 Step 4, mutation-proved at Step 6.
- The live aggregation defect → Task 2, with both controls the PO fix needed (different lines pass;
  exactly-at-ceiling passes).
- Cross-vendor refusal at the route, not the picker → Task 2 Step 1.
- Migration on a real-DB copy → Task 6 Step 2.
- Blocking browser pass → Task 7.

Type consistency: `purchase_orders` / `po_number_display` (Task 1) are used by Tasks 4-5;
`assert_payload_within_open_qty(pairs, exclude_rr_id)` (Task 2) is used by Tasks 2-3;
`_eligible_purchase_orders(branch_id, vendor_id)` (Task 3) is used by Task 4. No name drifts.

No placeholders: every code step carries the code. No step states an expected pass count.
