# Customer PO Required (per-customer) — Design

**Date:** 2026-07-08 · **Roadmap:** R-01 Sales (Order-to-Cash) · **Status:** proposed

## Goal

Let a customer be flagged as **"Purchase Order required."** When such a customer's Sales Order is
**confirmed**, the SO's Customer PO # must be filled — otherwise the confirmation is blocked. Customers
without the flag behave exactly as today (PO optional).

## Rationale

Some customers only authorize a sale via a formal Purchase Order; confirming their SO without a PO on
file is a control gap. Making it a **per-customer** flag (not a global rule) matches reality — many
customers order without a PO. Enforcement lands at **Confirm** (the commitment), not at draft creation,
so a draft can still be captured incomplete.

## Scope decisions (locked)

- Enforces the **PO number** only — the PO **date** stays optional.
- The rule fires **only on Confirm** (draft → confirmed). Creating/editing/saving a draft is unaffected.
- Uses the customer's **current** `po_required` flag and the SO's stored `customer_po_number`.

## Architecture / components

### Model (change — this spec is the approval request)
- `app/customers/models.py::Customer`: add
  `po_required = db.Column(db.Boolean, default=False, nullable=False)` and
  `'po_required': self.po_required` to `to_dict()`. Default `False` keeps every existing customer
  unaffected.

### Migration (hand-written, batch)
- One migration adds the `po_required` column: `op.batch_alter_table('customers')` →
  `add_column(sa.Column('po_required', sa.Boolean(), nullable=False, server_default=sa.false()))`,
  then `alter_column('po_required', server_default=None)`. `down_revision = 'b7780a041539'`.
  Verify on a copy of `cas.db`, then apply.

### Customer form + view
- `CustomerForm`: add `po_required = BooleanField('Requires Purchase Order')` (import `BooleanField`).
- Customer create/edit view: persist `customer.po_required = bool(form.po_required.data)` (mirror the
  existing `is_active` handling); pre-fill the checkbox on edit.
- Customer form template: a checkbox with the hint "When set, a Purchase Order number is required before
  a Sales Order for this customer can be confirmed." (mirror the salesperson/minimum-wage checkbox
  markup).

### SO confirm guard
- `app/sales_orders/views.py::confirm()`: after the existing role + `status == 'draft'` checks and
  **before** flipping the status, add:
  ```python
  if so.customer and so.customer.po_required and not (so.customer_po_number or '').strip():
      flash(f'Customer "{so.customer_name}" requires a Purchase Order number before this '
            f'Sales Order can be confirmed.', 'error')
      return redirect(url_for('sales_orders.view', id=id))
  ```
  (`so.customer` is the existing relationship.) No other confirm behaviour changes.

## Testing (TDD)

- **Model:** Customer constructs with/without `po_required`; `to_dict()` carries it.
- **Migration:** `flask db upgrade` on a copy of `cas.db` → column present, existing rows intact.
- **Confirm guard (integration):**
  - PO-required customer + **blank** `customer_po_number` → POST confirm → SO **stays draft**, flash
    shown, no `confirmed_at`.
  - PO-required customer + PO filled → confirm **succeeds** (status confirmed).
  - Non-flagged customer + blank PO → confirm **succeeds** (unchanged behaviour).
- **Customer form:** create/edit persists `po_required`; checkbox reflects the saved value.

## Blast radius

`Customer` model (+ `to_dict`) + one migration; `CustomerForm` + its create/edit view + form template;
`sales_orders.confirm`. Existing customer CRUD tests are unaffected (new column is optional/defaulted).
Regression-map: `customers` + `sales_orders` already mapped.

## Out of scope

- Requiring the PO **date**.
- A live form hint on the SO create/edit page when a PO-required customer is picked (UX polish; the
  server-side confirm guard is the safety net — deferrable).
- Applying a PO requirement to other documents (SI, etc.).
