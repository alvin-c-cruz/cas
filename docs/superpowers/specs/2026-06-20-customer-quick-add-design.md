# Inline "Add Customer" Quick-Add — Design Spec

**Date:** 2026-06-20
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** Give the customer picker on the Sales Invoice and Cash Receipt forms an inline
"Add Customer" quick-add, functionally and visually mirroring the existing vendor quick-add
on the AP / Cash Disbursement forms.

## Goal

On `/sales-invoices/create` (and `/sales-invoices/<id>/edit`) and the Cash Receipt
(CRV) create/edit forms, the customer picker should behave like the vendor picker in the
AP voucher: a searchable Choices.js select with a pinned **"➕ Add Customer…"** action that
opens a modal, creates the customer via AJAX, and auto-selects it without leaving the form.
The picker and modal should match the vendor field's styling.

## Reference implementation (the pattern being mirrored)

- **Modal:** `app/vendors/templates/vendors/_quick_add_modal.html` — overlay including
  `vendors/_form_fields.html`, POSTs to `vendors.create`.
- **JS:** `app/static/vendor-quick-add.js` → `initVendorQuickAdd({selectEl})`. Uses the shared
  `initSearchSelect` (`app/static/search-select.js`) with
  `addAction {value:'__add_vendor__', label:'➕ Add Vendor…', onSelect: openModal}`. On AJAX
  success it `setChoices` + `setChoiceByValue` for the new vendor, then dispatches a native
  `change` on the underlying `<select>` so the page's vendor handler fires.
- **Backend:** `vendors/views.py::create()` uses `_wants_json()` (X-Requested-With == XMLHttpRequest
  or Accept: application/json). On success returns `jsonify(ok=True, vendor={'id', 'label'})`; on
  duplicate/validation error returns `jsonify(ok=False, errors={field: msg}), 422`. The same
  endpoint serves both HTML and JSON.
- **View context:** the AP view builds `vendor_quick_add_form = VendorForm()` (choices populated,
  code pre-generated, defaults set) + `vendor_quick_add_whts`, in **every** render path
  (create GET, edit, and each POST-bounce re-render). The AP form
  `{% include "vendors/_quick_add_modal.html" %}` + loads `search-select.js` and
  `vendor-quick-add.js` + calls `initVendorQuickAdd({selectEl: vendorSel})`.

## Decisions (from brainstorming)

1. **Access:** loosen `customers.create` to **staff_or_above** (matching vendors). Staff can then
   create customer master data app-wide. Edit/delete keep their current accountant/admin gates.
2. **Scope:** wire the quick-add into **both** customer-side transaction forms — Sales Invoice **and**
   Cash Receipt (full parity with vendor quick-add covering AP + CD).
3. **Approach:** **faithful mirror** (Approach A) — parallel customer files, reusing the shared
   `initSearchSelect`; do not refactor/touch the working vendor path.
4. **Modal contents:** the **full** customer form (mirrors the vendor modal), not a trimmed version.

## Components

### 1. Backend — `app/customers/views.py`

- Add `_wants_json()` (verbatim mirror of the vendor helper).
- Add a `staff_or_above_required` decorator mirroring `vendors/views.py` (customers currently only
  has `accountant_or_admin_required`).
- `create()`:
  - Decorator `@accountant_or_admin_required` → `@staff_or_above_required`.
  - Duplicate-code path: `return jsonify(ok=False, errors={'code': '…already exists.'}), 422` when
    `_wants_json()`, else existing flash + HTML re-render.
  - Success path: after `log_create` + commit, `return jsonify(ok=True, customer={'id': customer.id,
    'label': f'{customer.code} - {customer.name}'})` when `_wants_json()`, else existing redirect.
  - Invalid form on a JSON POST: `return jsonify(ok=False, errors={f: errs[0] for f, errs in
    form.errors.items()}), 422`.
- No model change. Audit logging is unchanged (the same `create()` path runs `log_create`).

### 2. New file — `app/customers/templates/customers/_quick_add_modal.html`

Mirror of the vendor modal:
- `#customerQuickAddOverlay` (design-token styling identical to the vendor overlay).
- `<h3>Add Customer</h3>`, close button, `#customerQuickAddError` box.
- `<form id="customerQuickAddForm" method="POST" action="{{ url_for('customers.create') }}" novalidate>`
  with a CSRF hidden input and `<div class="customer-form-scope">` wrapping
  `{% with form = customer_quick_add_form, customer = None %}{% include "customers/_form_fields.html" %}{% endwith %}`.
- Footer: Cancel + **"Create Customer"** submit (master-data verb; note the vendor modal's
  "Save Vendor" is the known convention violator — the customer modal uses the correct verb).
- Requires `customer_quick_add_form` in the template context.

### 3. New file — `app/static/customer-quick-add.js`

`initCustomerQuickAdd({selectEl})`, mirror of `vendor-quick-add.js`:
- Builds the picker via `initSearchSelect(selectEl, { choicesOptions:{searchResultLimit:50},
  addAction:{ value:'__add_customer__', label:'➕ Add Customer…', onSelect: openModal } })`.
- `openModal` inits the modal's VAT + WT search-selects once via `initCustomerVatSelect(overlay)` /
  `initCustomerWtSelect(overlay)` (from `customer-form-widgets.js`), keeping the instances to reset
  after save.
- On submit: `fetch(action, {method:POST, body:FormData, headers:{'X-Requested-With':'XMLHttpRequest'}})`;
  on `ok` → `setChoices` + `setChoiceByValue` for the new customer, dispatch native `change`, close +
  `form.reset()` + clear the Choices-managed VAT/WT widgets; on error → show first error in the box.

### 4. SI wiring — `app/sales_invoices/`

- `views.py`: a small helper `_customer_quick_add_form()` returning a populated `CustomerForm`
  (`populate_dropdown_choices` + `generate_next_customer_code()` + `is_active='1'` +
  `payment_terms='Net 30'`); pass `customer_quick_add_form=…` to `render_template` in **all** SI
  form render paths (create GET, edit GET, and every POST-bounce re-render).
- `form.html`: `{% include "customers/_quick_add_modal.html" %}`; add
  `<script src="search-select.js">` + `<script src="customer-quick-add.js?v=1">`; replace the plain
  `new Choices(customerSel, …)` with `initCustomerQuickAdd({selectEl: customerSel})`; add an
  `if (cid === '__add_customer__') return;` guard to the existing customer-select handler (which
  reveals line items + adds the first line).

### 5. CRV wiring — `app/cash_receipts/`

- `views.py`: build `customer_quick_add_form` in the CRV create/edit/bounce render paths (CRV has
  `restore_ar_lines` / `restore_revenue_lines` bounce paths).
- `form.html`: include the modal; add the two scripts; route `#customer_id` through
  `initCustomerQuickAdd`; guard `onCustomerChange` against `__add_customer__` (it must not fetch
  open invoices for the sentinel value).

### 6. CSS + required front-end assets per host form

No new CSS file, but the customer-side transaction forms do **not** currently load the customer-form
assets (SI loads `accounts_payable_form.css` + `transactions.css`; neither SI nor CRV loads
`customer-form.css`). The modal + picker need these on **each** host form (SI form.html, CRV form.html):

- `customer-form.css` (`<link>`, with `?v=`) — modal field styling (`.customer-form-scope`).
- `customer-form-widgets.js` (`<script>`) — `initCustomerVatSelect` / `initCustomerWtSelect` for the
  modal's VAT/WT selects.
- `search-select.js` + `customer-quick-add.js?v=1` (`<script>`) — the picker + quick-add wiring.
- The modal's `status_toggle(form.is_active)` macro needs `initStatusToggle()` (from `cas-ui.js`, loaded
  via base.html) to run against the modal toggle — confirm it initialises modal toggles (or call it on
  modal open). See [[shared-status-toggle]].

The picker itself matches the vendor field because it now uses the same `initSearchSelect`. Precedent:
the AP form loads `vendor-form.css` so its `.vendor-form-scope` modal renders correctly — the customer
forms must load `customer-form.css` for the same reason.

## Data flow

1. User opens the customer picker → sees existing customers + a pinned "➕ Add Customer…" item.
2. Selecting that item fires `addAction.onSelect` → modal opens (VAT/WT selects initialised once).
3. User fills the form (only code + name are required; `default_vat_category` is Optional) → submits.
4. `customer-quick-add.js` AJAX-POSTs to `customers.create` with `X-Requested-With`.
5. View `create()` validates, persists, `log_create`, returns `jsonify(ok=True, customer={id,label})`.
6. JS injects the new option, selects it, dispatches `change` → the form's customer handler runs
   (SI: reveal line items + add first line; CRV: fetch open invoices). Modal closes; form resets.
7. On validation error: `422 {errors}` → first error shown in the modal; modal stays open.

## Error handling

- Duplicate code → `422 {code: '…already exists.'}` → shown in modal.
- WTForms validation error → `422 {field: first-msg}` → shown in modal.
- Network failure → JS shows "Network error — customer was not created."; submit button re-enabled.
- Sentinel `__add_customer__` never reaches a fetch (guarded in both form handlers).

## Testing (TDD)

- **e2e (Playwright)** — new `tests/e2e/test_si_smoke.py` case (mirror AP's
  `test_quick_add_modal_opens_and_selects_new_vendor`): open the customer picker, click "Add Customer",
  fill name (+ VAT if needed), submit, assert modal closes, the new customer is the selected chip, and
  the line-items section is revealed. Add the equivalent for CRV (new `tests/e2e/test_crv_smoke.py` or
  extend an existing CRV e2e). Requires a `SalesVATCategory` seeded in `tests/e2e/_serve.py` if the
  modal's VAT select must be exercised (confirm seed_minimal already seeds sales VAT categories; C001
  customer is already seeded).
- **Integration** — `customers.create` JSON branch: POST with `X-Requested-With` returns
  `ok=True` + customer JSON (200) for valid input and `422` + `errors` for invalid/duplicate. Assert the
  audit entry is still written on the JSON path.
- **Access change** — add a test that **staff** can POST `customers.create` (now allowed); update/replace
  any existing test that asserts staff is *blocked* from `customers.create` (stale after the loosening).

## Ripple effects / risks

- **Access-policy change** (staff → can create customers): the only app-behavior change beyond the new
  UI. Find and update stale tests asserting staff is blocked. Document in the implementation plan.
- **Multiple render paths**: SI and CRV each build the quick-add context in several places; missing one
  leaves an empty modal on that path. Mirror AP's all-paths discipline; a test that loads each form and
  asserts the modal's code field is pre-filled guards this.
- **`__add_customer__` guards** on the SI handler and CRV `onCustomerChange`.
- **Code-uniqueness race**: two concurrent quick-adds can collide on the generated code → the unique
  constraint raises, surfaced as a `422`. Same behavior as vendor; acceptable.
- **Cache-busters**: new `customer-quick-add.js?v=1`; bump if later edited. `search-select.js` is reused
  unchanged.
- **CRV parity** ([[cdv-crv-parity-mirror]] / [[customers-vendors-parity-mirror]]): doing SI + CRV together
  keeps the customer-side forms in sync and closes the "customers lacks a quick-add modal" gap.

## Out of scope

- Customers **list** page quick-add (the list keeps its full-page "Create" button).
- Refactoring vendor + customer quick-add into one shared module (Approach B).
- The SI customer card's `vendor-step-card` class naming (cosmetic inconsistency; not visual-breaking).
- AP's `restore_lines` re-hydration on SI (tracked separately as backlog item 31).
