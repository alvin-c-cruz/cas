# Record Status Design — Purchase Bills & Sales Invoices

**Date:** 2026-06-09
**Scope:** `app/purchase_bills/`, `app/sales_invoices/`
**Approach:** Status layer only (no JE automation on post — void only)

---

## Problem

Posted bills and invoices have no correction path. Once posted, a record with an error is permanently stuck — there is no void, no reversal, and cancel is only wired for drafts. This is a compliance and operational gap.

---

## Status Model

### Purchase Bills

```
Draft ──→ Posted ──→ Partially Paid ──→ Paid
  │          │            │
  ↓          ↓            │ (reverse payment first)
Cancelled  Voided ←───────┘
```

### Sales Invoices

```
Draft ──→ Sent ──→ Posted ──→ Partially Paid
  │         │        │              │
  ↓         ↓        ↓              │ (reverse payment first)
Cancelled Cancelled Voided ←────────┘
```

### Overdue

Not a stored status. Computed: `due_date < today AND status IN ('posted', 'partially_paid')`. Displayed as an orange badge on list and detail views. No DB column, no migration.

---

## Transition Rules

| From | To | Roles | Condition |
|---|---|---|---|
| Draft | Posted (bills) | Accountant, Admin | — |
| Draft | Sent (invoices) | Accountant, Admin | — |
| Sent | Posted (invoices) | Accountant, Admin | — |
| Draft | Cancelled (bills) | Accountant, Admin | `amount_paid == 0` |
| Draft / Sent | Cancelled (invoices) | Accountant, Admin | `amount_paid == 0` |
| Posted | Voided | Accountant, Admin | `amount_paid == 0` |
| Posted | Partially Paid / Paid | System (via Receipts) | — |

Paid and Partially Paid records **cannot** be voided. The accountant must reverse the payment first, which returns the record to Posted, then void. **Dependency:** the Receipts & Payments module must transition the bill/invoice back to `posted` (or `partially_paid`) when a payment is reversed — this is a prerequisite for the void flow to work on partially-paid records.

---

## Model Changes

### `PurchaseBill` — new fields

| Field | Type | Nullable | Purpose |
|---|---|---|---|
| `voided_at` | DateTime | Yes | PH timestamp of void |
| `voided_by_id` | FK → User | Yes | User who performed void |
| `void_reason` | String(255) | Yes | Required reason entered by accountant |

Status column allowed values: `draft`, `posted`, `partially_paid`, `paid`, `cancelled`, `voided`

### `SalesInvoice` — new fields

| Field | Type | Nullable | Purpose |
|---|---|---|---|
| `sent_at` | DateTime | Yes | PH timestamp when marked Sent |
| `sent_by_id` | FK → User | Yes | User who marked Sent |
| `voided_at` | DateTime | Yes | PH timestamp of void |
| `voided_by_id` | FK → User | Yes | User who performed void |
| `void_reason` | String(255) | Yes | Required reason entered by accountant |

Status column allowed values: `draft`, `sent`, `posted`, `partially_paid`, `paid`, `cancelled`, `voided`

### Migration

Two `ALTER TABLE` statements — additive nullable columns only. Safe on existing data, no backfill required.

---

## New Routes

### Purchase Bills

| Route | Method | Guard | Action |
|---|---|---|---|
| `/purchase-bills/<id>/void` | POST | `status == 'posted'`, `amount_paid == 0` | Void bill, create reversal JE, audit log |

### Sales Invoices

| Route | Method | Guard | Action |
|---|---|---|---|
| `/sales-invoices/<id>/send` | POST | `status == 'draft'` | Mark as Sent |
| `/sales-invoices/<id>/void` | POST | `status == 'posted'`, `amount_paid == 0` | Void invoice, create reversal JE, audit log |

All guards are enforced server-side regardless of UI state.

---

## Void Modal (UI)

HTML form modal — no `confirm()` or `alert()` (per project rules). Contains:

1. **Void Reason** — text input, required, minimum 10 characters
2. **Reversal Date** — date input, pre-filled with today (PH time), editable
3. Hidden CSRF token: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
4. Cancel button (closes modal, no action)
5. Confirm button: "Void this Record" (red, submits POST)

---

## Reversal Journal Entry

Created automatically when void is confirmed. Exactly mirrors the original posting entries with signs flipped.

**Example — Purchase Bill void:**
```
Purchase Bill Void — PB-2026-0001 (reversal)
  DR  Accounts Payable          ₱3,920.00
  CR  Office Supplies Expense   ₱3,500.00
  CR  Input VAT                   ₱420.00
```

**Example — Sales Invoice void:**
```
Sales Invoice Void — SI-2026-0001 (reversal)
  DR  Revenue                   ₱X,XXX.00
  DR  Output VAT                  ₱XXX.00
  CR  Accounts Receivable       ₱X,XXX.00
```

**JE metadata:**
- `reference`: `VOID-{bill_number}` or `VOID-{invoice_number}`
- `entry_date`: reversal date entered by accountant (defaults to today PH time)
- `notes`: void reason
- `branch_id`: same as original record
- `created_by_id`: user who voided

**Failure behavior:** If required GL accounts (AP, AR, Input VAT, Output VAT) are not found in the COA, void fails with a clear flash error. It does not silently skip the JE.

---

## Audit Trail

| Event | `module` | `action` | `notes` |
|---|---|---|---|
| Bill voided | `purchase_bill` | `void` | `"Voided by {username}. Reason: {void_reason}"` |
| Invoice voided | `sales_invoice` | `void` | `"Voided by {username}. Reason: {void_reason}"` |
| Invoice sent | `sales_invoice` | `send` | `"Marked as sent by {username}"` |

---

## UI Status Display

| Status | Badge color | Action buttons shown |
|---|---|---|
| Draft | Grey | Post, Edit, Delete, Cancel |
| Sent (invoices) | Blue | Post, Cancel |
| Posted | Blue | Void (if `amount_paid == 0`) |
| Partially Paid | Yellow | — |
| Paid | Green | — |
| Cancelled | Red | — |
| Voided | Dark grey | — |
| + Overdue overlay | Orange pill | (added to Posted or Partially Paid) |

Voided detail page shows additional footer line: `Voided by {username} on {date} — Reason: {void_reason}`

---

## Out of Scope

- Journal entry creation on *post* (bill/invoice posting does not auto-generate JEs in this phase)
- Reversing payments as part of the void flow (accountant must reverse payments manually first)
- Period locking / closed-period enforcement
- Configurable GL account mapping (AP, AR, VAT accounts are resolved from known COA codes initially)
