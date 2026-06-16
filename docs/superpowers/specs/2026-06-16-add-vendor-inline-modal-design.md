# Design: "+ Add Vendor" inline modal on transaction vendor pickers

**Date:** 2026-06-16
**Status:** Approved (design) — pending implementation plan
**Author:** alvin-c-cruz (with Claude Code)

## Problem

On transaction pages that pick a vendor (starting from
`http://127.0.0.1:5000/accounts-payable/create`), users can only choose from
vendors that already exist. If the vendor is missing, they must abandon the
half-filled transaction, navigate to the full vendor page, create the vendor,
then start the transaction over. The vendor search-select should offer an
**"Add Vendor"** option so a new vendor can be created without leaving the page.

## Scope

Add a pinned **"➕ Add Vendor…"** option at the top of the vendor Choices.js
search-select. Selecting it opens a CSRF-protected HTML modal containing the
**full** vendor form. On save, the vendor is created via an AJAX endpoint,
added to the dropdown, and auto-selected — the in-progress transaction is never
lost.

Applies to the two transaction modules with a `vendor_id` Choices.js picker:

- **Accounts Payable** — create + edit (`app/accounts_payable/templates/accounts_payable/form.html`)
- **Cash Disbursements** — create + edit (`app/cash_disbursements/templates/cash_disbursements/form.html`)

**Out of scope:** Sales Invoices and Receipts use a *customer* picker, not
vendor/payee. A "+ Add Customer" equivalent would be a separate, later feature.

## Components

### a. Shared vendor-form partial — `app/vendors/templates/vendors/_form_fields.html`
Extract the field markup (currently rows 16–169 of `vendors/form.html`) into a
partial. The full vendor page includes it (no behavior change), and the modal
includes it too. This is the DRY anchor so the two never drift. The VAT
search-select and WHT-checkbox JS currently inline in `form.html` move into a
shared scope so they also work inside the modal.

### b. Modal partial — `app/vendors/templates/vendors/_quick_add_modal.html`
A hidden full-screen overlay (design-token styling, **no hardcoded colors**)
wrapping a `<form>` with `{{ csrf_token() }}`, the `_form_fields.html` include,
and Cancel / **Create Vendor** buttons. Included once per host page (AP form,
CD form).

### c. Shared JS — `app/static/vendor_quick_add.js`
One init function both AP and CD `form.html` call. It:
- pins the `__add_vendor__` sentinel choice at the top of the picker;
- intercepts the select's `change` — if the value is the sentinel, open the
  modal and revert the selection to the placeholder;
- submits the modal form via `fetch`;
- on success, injects the new vendor into the page's existing Choices instance,
  selects it, and dispatches the normal `change` event so downstream logic runs
  (AP loads WHT/VAT/terms defaults via `/vendors/<id>/defaults`; CD runs its
  open-bills fetch, which returns empty for a brand-new vendor).

### d. JSON-aware create endpoint — `app/vendors/views.py`
Extend the existing `create()` view (remains `@staff_or_above_required`) to
detect an AJAX request (`Accept: application/json` / `X-Requested-With`):
- **Success:** return `{ "ok": true, "vendor": { "id": ..., "label": "V012 - Acme" } }`.
- **Validation / duplicate-code error:** return `{ "ok": false, "errors": {...} }`
  with HTTP 422.

The existing HTML path (redirect to vendor list on success, re-render form on
error) is unchanged. **Audit logging (`log_create`) fires identically on both
paths.** Vendor code auto-generation (`V###` via `generate_next_vendor_code`)
is reused unchanged.

## Data flow

1. User picks "➕ Add Vendor…" → modal opens, picker resets to placeholder.
2. User fills the full vendor form → submits → `fetch` POST to `/vendors/create`.
3. **Success** → modal closes; vendor appended to Choices, selected; `change`
   event fires → downstream defaults load; brief confirmation toast
   ("Vendor V012 created").
4. **Failure** → field errors render inside the modal; transaction data
   untouched.

## Error / edge handling

- Duplicate code or validation error → HTTP 422 + inline errors in the modal,
  no page reload.
- CSRF token is included in the modal form and sent with the AJAX request.
- Permission: both host pages and vendor-create are already `staff+`, so no new
  gate is introduced; viewers never reach these create/edit pages.
- A new vendor on a Cash Disbursement has no open bills — expected; the existing
  open-bills fetch returns empty gracefully.

## Testing

- **Endpoint unit/integration:**
  - AJAX success → JSON body + vendor row created + **audit entry asserted**
    (correct action, record reference, actor).
  - AJAX duplicate code / invalid → HTTP 422 + no row created.
  - HTML path still redirects on success (regression guard).
  - Viewer / unauthenticated → denied.
- **Integration:** the existing full vendor page still renders correctly after
  the `_form_fields.html` extraction.
- **Manual / Playwright:** open modal → fill → save → vendor auto-selected on
  the transaction; account for the readonly-password anti-autofill quirk where
  relevant.

## Ripple effects checked

- **Views:** AP and CD views untouched; only `app/vendors/views.py` changes.
- **Audit log:** preserved on both create paths.
- **Cache:** no vendor cache exists (`cache_helpers` covers accounts, VAT, WHT,
  branches only) — nothing to invalidate.
- **Approval workflow:** vendors are created directly (not a `*ChangeRequest`
  entity), so no change-request flow is involved.
- **Document numbering:** auto `V###` reused.
- **Picker sites:** AP create, AP edit, CD create, CD edit — all share one JS
  module and one modal partial.

## Open decisions (resolved during brainstorming)

- **Creation mechanism:** inline modal (stay on page) — chosen over redirect, to
  avoid losing in-progress transaction data.
- **Modal fields:** full vendor form — chosen over minimal/name-only, for
  complete data capture.
- **Reach:** all transaction vendor/payee pickers (AP + CD) — chosen over
  AP-only.
- **Affordance:** an option inside the search-select (per the original request),
  not a separate button.
- **Endpoint shape:** extend existing `create()` with content negotiation,
  rather than a separate `/vendors/create-ajax` route.
