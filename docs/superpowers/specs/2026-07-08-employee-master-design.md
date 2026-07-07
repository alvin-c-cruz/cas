# Employee Master + Combined Payee Dropdown — Design Spec

**Date:** 2026-07-08
**Status:** Draft — awaiting user review
**Slice:** Payroll arc, slice 1 (see "Payroll arc & future work")
**Author:** brainstorming session (alvin + Claude)

## Motivation

Recording the owner's June salary surfaced an awkwardness: to pay a salary, a
person had to be set up as a **vendor** (today "Alvin C. Cruz" is literally a
`vendors` row, `V001`). That conflates two different BIR regimes:

- **Vendor payments** -> creditable/expanded withholding (BIR 2307, 1601-EQ,
  supplier Alphalist), reported through the Purchases / expanded-withholding book.
- **Employee compensation** -> withholding on compensation (BIR 1601-C, 2316),
  plus SSS / PhilHealth / Pag-IBIG, 13th-month, graduated tax tables.

The goal is a **foundation for real payroll**. This slice delivers the Employee
master **and** a combined payee picker on the AP voucher (vendors + employees in
one dropdown, chosen deliberately after reviewing the trade-offs), with
**employee-payee vouchers segregated** out of vendor/BIR-supplier reports.

## Decisions locked in this session

1. First driver: **foundation for real payroll** (not just a fake-vendor workaround).
2. Employee field set: **payroll-ready core** (identity + gov IDs + employment +
   tax + compensation), so later payroll slices need no identity migration.
3. Optional **Employee <-> User** link (identity mapping only; see non-derivation).
4. Employee master is an **opt-in module** in `MODULE_REGISTRY`.
5. Payee picker: **combined dropdown** (vendors + employees), NOT vendor-only.
6. Employee-payee vouchers are **segregated** from vendor AP aging, BIR
   Purchases / 1601-EQ, and supplier Alphalist.
7. Storage: **polymorphic payee** on `AccountsPayable`; **keep `vendor_id`
   (nullable)** rather than dropping it (rationale below).
8. Employee-payee vouchers carry **no auto WHT** for now (manual), matching how
   the June salary was booked. Compensation-WHT automation is a future slice.
9. One-person-many-roles (vendor/customer/employee): **deferred** (Approach C).
   A unified Party model is a separate future initiative; customers are NOT in
   the payee dropdown.

## Scope

### In scope
- `Employee` model (`app/employees/`), fields per "Data model".
- New `app/employees/` blueprint (CRUD: list / create / edit / toggle-status),
  mirroring `app/vendors/`. Opt-in module.
- `employee_no` auto-generation (`EMP-####`), editable.
- **`AccountsPayable` polymorphic payee**: `payee_type` + `payee_id`, `vendor_id`
  made nullable, backfilled.
- **Combined payee dropdown** on the APV form (vendors + employees, badged),
  inline Add Vendor / Add Employee.
- **Segregation** of employee-payee vouchers from vendor/BIR-supplier reports.
- Hand-written batch Alembic migrations, verified on a copy of real `cas.db`.
- Full TDD coverage incl. audit-log + segregation regression tests, then `/guard`.

### Out of scope (later slices / initiatives)
- Payroll/salary voucher + its GL posting; compensation-WHT tables; statutory
  contribution tables; payslips / 13th-month / de-minimis; BIR 1601-C / 2316 /
  compensation Alphalist.
- **Unified Party/Contact model** (one identity, many role profiles). Deferred;
  its own future initiative. Recorded here so the intent isn't lost.
- Adding **customers** to the payee dropdown (they are sales-side, not payees).

## Data model

### `Employee` (`__tablename__ = 'employees'`)
All columns nullable unless noted.

| Group | Field | Type | Notes |
|---|---|---|---|
| Identity | `id` | Integer PK | |
| | `employee_no` | String(20), unique, NOT NULL, indexed | `EMP-####`, auto-gen, editable |
| | `first_name` | String(100), NOT NULL | |
| | `middle_name` | String(100) | |
| | `last_name` | String(100), NOT NULL | |
| | `birthdate` | Date | |
| | `address` | Text | |
| | `phone` | String(50) | |
| | `email` | String(120) | |
| Gov IDs | `tin` | String(50) | |
| | `sss_no` | String(50) | |
| | `philhealth_no` | String(50) | |
| | `pagibig_no` | String(50) | |
| Employment | `date_hired` | Date | |
| | `employment_status` | String(30) | regular / probationary / contractual / part-time |
| | `position` | String(120) | **Free-form HR job title** (non-derivation rule) |
| Scope | `branch_id` | Integer FK `branches.id`, **NOT NULL**, indexed | branch-scoping rule |
| Tax | `tax_status_code` | String(10) | e.g. S, ME, ME1 ... |
| | `qualified_dependents` | Integer, default 0 | |
| | `is_minimum_wage` | Boolean, default False | |
| Compensation | `pay_basis` | String(20) | monthly / daily |
| | `basic_rate` | Numeric(12,2) | |
| | `pay_frequency` | String(20) | monthly / semi-monthly |
| Link/status | `user_id` | Integer FK `users.id`, **nullable**, indexed | optional identity link |
| | `is_active` | Boolean, default True, NOT NULL | |
| Audit | `created_at`, `updated_at` | DateTime (PH time) | match sibling models |

Helpers: `full_name` property; `to_dict()` reading **columns only** (no lazy
relationship reads -- cache-detached trap); `branch` relationship.

**Non-derivation rule (position vs. user role).** `User.role` (admin / accountant
/ staff / viewer) is application **authorization**; `Employee.position` is an HR
**job title**. Orthogonal -- the same person can be an `admin` user whose position
is "Managing Partner." `position` is plain text, never a dropdown of user types,
never derived from / synced with `User.role`. The optional `user_id` link is pure
identity mapping and carries no role/position meaning.

### `AccountsPayable` changes (polymorphic payee)
| Field | Change | Notes |
|---|---|---|
| `payee_type` | **ADD** String(20), NOT NULL, default `'vendor'` | `'vendor'` \| `'employee'` |
| `payee_id` | **ADD** Integer, NOT NULL | id within the payee table |
| `vendor_id` | **ALTER** -> nullable (was NOT NULL) | set for vendor payees, NULL for employees |

- **Backfill migration:** every existing row -> `payee_type='vendor'`,
  `payee_id = vendor_id` (leave `vendor_id` populated).
- Add `payee` property -> resolves `Vendor` or `Employee` by `payee_type`.
- Keep a `vendor` property for back-compat (returns the `Vendor` when
  `payee_type=='vendor'`, else `None`).
- `to_dict()` gains `payee_type`, `payee_id`, and a resolved `payee_name`.

**Why keep `vendor_id` nullable instead of dropping it.** Segregation then falls
out almost for free: existing vendor/BIR-supplier reports already filter/join on a
vendor, so employee rows (`vendor_id IS NULL`) drop out automatically. Dropping the
column would force edits to every reader (aging, journals, exports, BIR book,
`to_dict`) with the column-drop-blast-radius risk of empty-DB tests going falsely
green. Keeping it nullable is the lower-risk path. (A future Party initiative can
retire it.)

## Module structure

New blueprint `app/employees/` mirroring `app/vendors/`:

```
app/employees/
  __init__.py
  models.py       # Employee
  forms.py        # EmployeeForm (WTForms)
  views.py        # list / create / edit / toggle_status
  utils.py        # generate_next_employee_no()  (mirror generate_next_vendor_code)
  templates/employees/
    list.html
    form.html
```

Registration (explicit lists in `create_app`, edited manually):
1. Import `Employee` in the model-import block (migration autodetect).
2. Register the `employees` blueprint.
3. Add an **opt-in** entry to `MODULE_REGISTRY`; gate views with module-access and
   show the sidebar link only when enabled.

`generate_next_employee_no()` mirrors `generate_next_vendor_code()`: sequence by the
numeric suffix of `EMP%` codes (not lexicographic), format `f'EMP-{n:04d}'` (4-wide,
still increments past 9999).

## UI / UX

### Employee master
- **List** (`list.html`): no, name, position, branch, status. Launch button
  **"Create Employee"** (master-data verb). **No empty-state CTA** -- plain
  "No employees found." only. Active/Inactive via `status_toggle()` macro +
  `initStatusToggle()`; reuse global `.badge-active` / `.badge-inactive`.
- **Form** (`form.html`): sections (Identity, Gov IDs, Employment, Tax,
  Compensation, Link). Submit **"Create"** / **"Update"**. Branch picker + optional
  User picker via `initSearchSelect` (Choices.js, `": "` separator); User link
  blank allowed. Design tokens only, responsive.
- **Delete**: explicit pre-check before delete (SQLite FK enforcement off
  app-wide) -- block if referenced by any AP voucher (`payee_type='employee'` and
  `payee_id=this`). Written and tested now so later slices can rely on it.

### Combined payee dropdown (APV form)
- Relabel **STEP 1 -- SELECT PAYEE**. Dropdown lists active vendors **and** active
  employees, each badged `[Vendor]` / `[Employee]`, shown `code : name`.
- Option value encodes type+id (`vendor:12`, `employee:3`); the form parses it into
  `payee_type` + `payee_id`. Server validates the referenced record exists and is
  active.
- Inline **Add Vendor** / **Add Employee** actions.
- On select: **vendor** -> load VAT / expanded-WHT defaults as today; **employee**
  -> **No VAT, no WHT** (manual), matching the June salary booking.
- Detail / list / print surfaces show the payee with its type badge (SI-surface
  consistency: create + edit + view + list + print must share the jargon).

```
Combined payee dropdown (APV):
+-- STEP 1 -- SELECT PAYEE --------------------------------+
|  search... [ Add Vendor ]  [ Add Employee ]             |
|  V001    : Alvin C. Cruz              [Vendor]          |
|  V002    : Anthropic, PBC             [Vendor]          |
|  EMP-0001 : Alvin C. Cruz             [Employee]        |
|  EMP-0002 : Maria Santos              [Employee]        |
+---------------------------------------------------------+
```

## Segregation (vendor/BIR-supplier reports)

Employee-payee vouchers (`payee_type='employee'` / `vendor_id IS NULL`) must be
excluded from vendor-facing reports:
- AP aging (supplier),
- BIR Purchases book / 1601-EQ (expanded WHT),
- supplier Alphalist,
- the vendor filter on the APV list.

Task: audit each of those queries; where a query does not already require a vendor
(e.g. a LEFT JOIN or a nullable path), add an explicit `payee_type == 'vendor'`
filter. Then run `/guard` over the AP blast radius. Each report gets a regression
test asserting an employee-payee voucher does **not** appear.

## Testing (TDD -- tests first)

- **Employee model:** unique `employee_no`; NOT-NULL `branch_id`; nullable
  `user_id`; `is_active` default; `full_name`; `to_dict()` columns-only.
- **Numbering:** `generate_next_employee_no()` sequences by numeric suffix, past
  9999, skips non-conforming codes.
- **Employee CRUD:** create/edit/list/toggle; audit-log assertion per write;
  branch scoping.
- **Polymorphic payee:** create APV for a vendor payee and for an employee payee;
  `vendor_id` NULL for employee; `payee` resolver returns the right object;
  `vendor` back-compat property.
- **Backfill migration:** run `flask db upgrade` on a **copy of real `cas.db`**;
  assert existing rows got `payee_type='vendor'`, `payee_id=vendor_id`, `vendor_id`
  preserved; assert `employees` table + unique index + NOT-NULL `branch_id` exist.
- **Form round-trip:** `vendor:ID` / `employee:ID` parse + persist + re-render on edit.
- **Segregation regression (per report):** an employee-payee voucher is absent from
  AP aging, BIR Purchases/1601-EQ, supplier Alphalist, and the vendor-filtered list.
- **Delete guard:** employee delete blocked when referenced by an AP voucher.
- **Module gating:** employee views 404 / sidebar hidden when the module is off.

## Suggested build order (one plan, staged)

1. **Employee master** -- model, CRUD, opt-in module, numbering. (Self-contained.)
2. **Polymorphic payee** -- add `payee_type`/`payee_id`, `vendor_id` nullable,
   backfill migration, `payee` resolver, back-compat `vendor`. (Verify on real-DB copy.)
3. **Combined dropdown UI** -- payee picker + inline add + per-type defaults +
   detail/list/print surfaces.
4. **Segregation audit + `/guard`** -- filter vendor/BIR reports, regression tests.

## Rejected / deferred alternatives

- **Vendor-only dropdown** (employees get a fully separate future picker): rejected
  in favor of the combined dropdown per user preference, made safe by segregation.
- **Full polymorphic drop of `vendor_id`:** deferred -- higher blast radius than
  keeping it nullable; a future Party initiative can retire it.
- **Unified Party/Contact model** (one person, many role profiles -- vendor +
  customer + employee): deferred (Approach C). Big refactor of two done modules;
  its own initiative. The "an employee can also be a customer" case is real but not
  urgent for a small firm; recorded for later.

## Payroll arc & future work (context only, not committed)

1. Employee master + combined payee dropdown  <- this spec.
2. Salary/payroll voucher + GL posting (Salaries / WHT-Compensation payable /
   statutory payables), separate from AP.
3. Compensation-WHT tables + statutory contribution tables (the calc engine).
4. Payslips, 13th-month, de-minimis.
5. BIR compensation reports (1601-C, 2316, compensation Alphalist).
6. (Separate track) Unified Party/Contact model.

Each is its own spec -> plan -> build cycle.
