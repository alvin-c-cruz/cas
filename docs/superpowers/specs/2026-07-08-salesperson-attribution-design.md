# Salesperson Attribution — Design

**Date:** 2026-07-08 · **Roadmap:** R-01 Sales (Order-to-Cash) · **Status:** proposed

## Goal

Record the **salesperson** (the sales rep responsible for the sale) on sales documents and carry the
name onto the **SI printout**. Today a Sales Order only has `created_by` — the user who *typed* the
order (an encoder/accountant), which is not the rep who made the sale — so there is no way to answer
"which rep sold this," run sales-by-agent reporting, or attribute commissions.

## Entity decision

**Salesperson = an `Employee`** (the Employee master built this session): a nullable FK to `employees`.
Chosen over a system `User` (not every rep has a login), a dedicated Sales-Agent master (no external-agent
requirement yet), or free-text (no integrity). Reuses the new master and sets up commissions /
sales-by-agent cleanly.

## Scope — v1 (buildable now)

- Add `salesperson_id` (nullable FK → `employees`) to the **Sales Order** and **Sales Invoice** headers.
- An **Employee picker** on the SO and SI create/edit forms, **gated on the Employees module**
  (`module_enabled('employees')`, optional/default-off) — mirrors how the Product picker is gated. When
  Employees is off, the field is absent and nothing is required.
- The **SI printouts** (standard `print.html`, pre-printed `print_preprinted.html`) and the SI detail
  view show the salesperson's `full_name` when set; blank otherwise.
- A small `copy_salesperson(src, dst)` helper is added so the future SO→DR→SI cascade is a one-line hook,
  but it is **not wired to any chain yet** (see below).

### Explicitly deferred
- **DR field + the auto-fill cascade (SO→DR→SI).** The cascade needs the order-to-cash **linkage, which
  is not built** (and DR does not exist yet). So v1 is the **field + manual entry** on SO and SI; the
  cascade wires up when DR and the linkage land — at which point DR gets the same field and
  `copy_salesperson` is called on create-from-upstream.
- Sales-by-agent reports, commissions, and an Order-Monitoring "by salesperson" breakdown (future).
- Salesperson on AP/CDV/CRV (those are not sales-rep documents).

## Architecture / components

### Models (change — this spec is the approval request)
- `app/sales_orders/models.py::SalesOrder`: add
  `salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)`
  and `salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])`. Add `salesperson_id`
  + `salesperson_name` (`self.salesperson.full_name if self.salesperson else None`) to `to_dict()`.
- `app/sales_invoices/models.py::SalesInvoice`: the same field + relationship + `to_dict()` keys.
- `nullable=True` — not every document has an assigned rep; keeps existing rows valid.

### Migration (hand-written, batch)
- One migration adds the nullable `salesperson_id` column (+ index) to `sales_orders` and
  `sales_invoices` via `op.batch_alter_table(...)` (SQLite, `render_as_batch` OFF). No FK enforcement
  worry (SQLite FKs are off app-wide). **Verify on a copy of `cas.db`** per `migration-verify-on-real-db-copy`.

### Forms & views
- `SalesOrderForm` / `SalesInvoiceForm`: add `salesperson_id = SelectField('Salesperson', coerce=int,
  validators=[Optional()], validate_choice=False)` (choices set in the view from active,
  branch-scoped employees). Create/edit persist `salesperson_id` (coerced, None when blank).
- The form context provides `employees` (active, current-branch) only when `module_enabled('employees')`;
  the template renders the picker inside `{% if module_enabled('employees') %}` using the shared
  search-select pattern (`initSearchSelect` / Choices, code+name display).
- `app/utils/` (or the sales_orders package): `copy_salesperson(src, dst)` — `dst.salesperson_id =
  src.salesperson_id`. Unit-tested; unused by any chain in v1.

### Printout / detail
- SI `print.html`, `print_preprinted.html`, and `detail.html`: render
  `{{ si.salesperson.full_name if si.salesperson else '' }}` in a labelled "Salesperson" slot. For the
  **pre-printed** form, add `'salesperson'` to the SI `FIELD_KEYS` in `preprinted_layout.py` and a
  positioned `.pp-el` in `print_preprinted.html` so it can be placed by the layout designer (blank when
  unset, like the other optional fields).

## Testing (TDD)

- **Model:** SO/SI construct with and without `salesperson_id`; `to_dict()` carries `salesperson_id`
  + `salesperson_name`; relationship resolves to the employee.
- **Migration:** `flask db upgrade` on a copy of `cas.db` → both columns present, existing rows intact.
- **Form/view:** SO/SI create with a salesperson persists it and audits; with Employees module **off**,
  the picker is absent and create still succeeds (salesperson null).
- **Printout:** SI `print.html` shows the employee `full_name` when set, and an empty slot when null.
- **Helper:** `copy_salesperson` copies the id.

## Blast radius

Models (`SalesOrder`, `SalesInvoice`) + `to_dict`; one migration; `SalesOrderForm` / `SalesInvoiceForm`
+ their create/edit views + form templates; SI `print.html` / `print_preprinted.html` / `detail.html` +
`preprinted_layout.py` SI `FIELD_KEYS`; existing SO/SI create tests are unaffected (field is optional).
Regression-map: `sales_orders` + `sales_invoices` already mapped.

## Out of scope

DR field & the SO→DR→SI auto-fill cascade (gated on the unbuilt chain), sales-by-agent reporting,
commissions, Order-Monitoring by-salesperson, and salesperson on non-sales documents.
