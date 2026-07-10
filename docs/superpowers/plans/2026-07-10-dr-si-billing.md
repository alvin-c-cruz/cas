# DR → SI Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans to implement this plan task-by-task. Steps use `- [ ]` checkboxes.

**Goal:** Bill delivered Delivery Receipts into a Sales Invoice from the SI create form.

**Architecture:** Additive picker on the existing SI form. Pulling a delivered DR appends its
lines (qty=delivered, price/VAT from the SO line, revenue = product default) as editable SI
lines; a request-only hidden `source_dr_ids` set drives billing. On SI create the DRs flip to
`billed` + `sales_invoice_id`; on void/cancel they revert. Consolidation is a company setting.

**Tech Stack:** Flask + SQLAlchemy 2.0 + Jinja + vanilla JS; pytest + Playwright.

## Global Constraints

- **No model change** — `DeliveryReceipt.sales_invoice_id` (existing) is the link; `source_dr_ids`
  is request-only. Do NOT add columns.
- Eligible DR: `status=='delivered'` AND `sales_invoice_id IS NULL` AND same customer + branch.
- Config: company setting `si_dr_billing_consolidate` (`'1'`/`'0'`, **default `'0'`=OFF**). OFF ⇒
  one DR per SI (guard `len(source_dr_ids) <= 1`); ON ⇒ many.
- Whole-DR billing only; same product across DRs stays separate lines.
- TDD; branch `feat/dr-si-billing` (already created off `main`); commit each task.
- No currency symbol in UI; no JS popups; SQLAlchemy 2.0 (`db.session.get`, not `.query.get`).

## File structure

- `app/sales_invoices/views.py` — `billable_drs` endpoint; `_bill_drs(si, dr_ids)` /
  `_unbill_drs(si)` helpers; hook create + void + cancel.
- `app/sales_invoices/templates/sales_invoices/form.html` — picker section + hidden
  `source_dr_ids`; load `app/static/js/si_dr_billing.js`.
- `app/static/js/si_dr_billing.js` — fetch `billable-drs`, pull → `addLineItem()` per line,
  maintain `source_dr_ids`, lock per `consolidate`.
- `app/company_settings/{forms.py,views.py,templates/company_settings/form.html}` — the toggle.
- Tests under `tests/integration/` + `tests/e2e/`.

---

### Task 1: `billable_drs` endpoint

**Files:** `app/sales_invoices/views.py`; test `tests/integration/test_si_billable_drs.py`.

**Interfaces — Produces:** `GET /sales-invoices/billable-drs?customer_id=<id>` →
`{consolidate: bool, drs: [{id, dr_number, delivery_date, lines: [{product_id, product_code,
product_name, quantity, unit_price, uom_display, vat_category, vat_rate, account_id}]}]}`.
Lines come from each `DeliveryReceiptItem.sales_order_item` (price/VAT) + `product.default_account_id`.

- [ ] **Step 1 — failing test:** seed a `delivered` DR (against a confirmed SO with a priced,
  V12 line) for customer C; assert `GET /sales-invoices/billable-drs?customer_id=C` returns that
  DR with a line whose `unit_price`/`vat_category`/`account_id` come from the SO line + product.
  Assert a `billed` DR and another customer's DR are excluded.
- [ ] **Step 2:** run → 404 (route missing).
- [ ] **Step 3 — implement:** `@login_required` route, branch from session, filter DRs
  (`status=='delivered'`, `sales_invoice_id is None`, `customer_id`, `branch_id`); build the JSON
  (reuse `DeliveryReceiptItem.sales_order_item` for qty/price/vat; `product.default_account_id`);
  include `consolidate` from `AppSettings.get_setting('si_dr_billing_consolidate','0')=='1'`.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 2: `si_dr_billing_consolidate` company setting

**Files:** `app/company_settings/forms.py`, `views.py`, `templates/company_settings/form.html`;
test `tests/integration/test_company_settings.py` (extend) or a new small test.

- [ ] **Step 1 — failing test:** POST the settings form with `si_dr_billing_consolidate='1'`;
  assert `AppSettings.get_setting('si_dr_billing_consolidate')=='1'`; default read is `'0'`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3 — implement:** add a `BooleanField`/select to `CompanySettingsForm`; add the key
  to the allowed-settings list in `company_settings/views.py`; render it in the settings template
  (grouped with the Sales-cycle toggles). Default `'0'`.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 3: SI create bills the DRs (+ consolidate guard)

**Files:** `app/sales_invoices/views.py` (create); test `tests/integration/test_si_dr_billing.py`.

**Interfaces — Consumes:** hidden `source_dr_ids` (JSON list) in the create POST.
**Produces:** `_bill_drs(si, dr_ids)` — validates each DR eligible (raises `ValueError` if not),
enforces consolidate guard, sets `dr.status='billed'`, `dr.sales_invoice_id=si.id`.

- [ ] **Step 1 — failing test:** POST `/sales-invoices/create` with a normal line + a valid
  `source_dr_ids=[dr.id]` (consolidate OFF); after, the DR is `billed` with `sales_invoice_id==si.id`.
  Second test: consolidate OFF + two dr_ids → SI not created, flash error. Third: consolidate ON +
  two → both billed.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3 — implement:** in `create()` (inside the try, after the SI + JE are built and
  `db.session.flush()` gives `si.id`, before commit), parse `request.form.get('source_dr_ids','[]')`;
  if non-empty call `_bill_drs(si, ids)`. `_bill_drs`: read consolidate setting; if OFF and
  `len(ids)>1` raise `ValueError('Consolidated billing is off — bill one Delivery Receipt per invoice.')`;
  for each id `db.session.get(DeliveryReceipt, id)`, assert eligible (branch, customer==si.customer_id,
  status=='delivered', sales_invoice_id is None) else raise; set billed + link. Errors roll back the
  whole create (existing `except ValueError` path).
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 4: SI void / cancel unbills the DRs

**Files:** `app/sales_invoices/views.py` (void + cancel); test extends `test_si_dr_billing.py`.

**Produces:** `_unbill_drs(si)` — every `DeliveryReceipt` with `sales_invoice_id==si.id` →
`status='delivered'`, `sales_invoice_id=None`.

- [ ] **Step 1 — failing test:** create an SI billing a DR (draft), then `void` it → the DR is
  back to `delivered`, `sales_invoice_id is None`. Repeat for `cancel` on a posted SI.
- [ ] **Step 2:** run → FAIL (void leaves DR billed).
- [ ] **Step 3 — implement:** call `_unbill_drs(si)` inside `void()` and `cancel()` before commit
  (query `DeliveryReceipt.query.filter_by(sales_invoice_id=si.id)`).
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 5: SI form picker UI + JS

**Files:** `app/sales_invoices/templates/sales_invoices/form.html`; `app/static/js/si_dr_billing.js`;
test `tests/integration/test_si_form_dr_picker.py` (render assertions).

- [ ] **Step 1 — failing test:** GET `/sales-invoices/create` (create form) → response contains the
  picker container (`id="drBillingSection"`) and a single hidden `name="source_dr_ids"`.
  *(Guard the BUG-DR-DUP-LINES class: exactly one `name="source_dr_ids"`.)*
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3 — implement:** add a collapsible "Bill delivered DRs" section (shown after a customer
  is chosen) with a hidden `source_dr_ids` input (rendered once). `si_dr_billing.js`: on customer
  change, `fetch('/sales-invoices/billable-drs?customer_id='+cid)`; render each DR as a "Pull" row;
  on Pull, for each DR line call the SI form's `addLineItem({...pre-filled...})`, push the DR id into
  `source_dr_ids`, remove that DR from the list; if `!consolidate`, disable further pulls once one is
  taken. Bump the `?v=` on the script tag. Reuse the existing `addLineItem` signature (read it in
  `form.html`). No JS popups.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 6: e2e smoke + regression-map

**Files:** `tests/e2e/_serve.py` (seed a delivered DR), `tests/e2e/test_si_dr_billing_smoke.py`;
`.claude/regression-map.json`.

- [ ] **Step 1:** extend the `sales` seed profile: from the seeded confirmed `SO-E2E-0001`, create an
  approved→delivered DR (so it's billable). 
- [ ] **Step 2 — e2e test:** login (sales profile) → `/sales-invoices/create` → pick customer C001 →
  the picker lists the delivered DR → Pull → SI line items populate with the delivered qty/price →
  save → SI created and the DR shows `billed`.
- [ ] **Step 3:** wire `sales_invoices` blast-radius: add `app/static/js/si_dr_billing.js` and the DR
  models to the map's `sales_invoices` dependents; ensure the SI e2e (or a new one) is referenced.
- [ ] **Step 4:** run the new integration + e2e; commit.

## Self-review notes

- **Spec coverage:** endpoint (T1), config (T2), bill-on-create + guard (T3), unbill-on-void/cancel
  (T4), picker UI/JS (T5), e2e (T6) — all spec sections covered.
- **Type consistency:** `source_dr_ids` is a JSON list of ints throughout; `_bill_drs`/`_unbill_drs`
  operate on `DeliveryReceipt`.
- **Risk:** T5 (SI form JS integration) is the hardest — read `form.html`'s `addLineItem` first and
  reuse it verbatim; keep the picker logic in its own `si_dr_billing.js`.

## Verification

- `pytest tests/integration/test_si_billable_drs.py test_si_dr_billing.py test_si_form_dr_picker.py -q`
- `pytest tests/e2e/test_si_dr_billing_smoke.py -m e2e`
- Manual/MCP: enable Sales-cycle modules; deliver a DR; on the SI form pick the customer, pull the DR,
  confirm lines + the DR flips to billed; void the SI → DR reverts.
- `/guard cas` before push (touches `sales_invoices` — high blast radius).
