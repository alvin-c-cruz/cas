# Employee Master — Design Spec

**Date:** 2026-07-08
**Status:** Draft — awaiting user review
**Slice:** 1 of the payroll arc (see "Payroll arc & future slices" below)
**Author:** brainstorming session (alvin + Claude)

## Motivation

Recording the owner's June salary surfaced an awkwardness: to pay a salary, a
person has to be set up as a **vendor** (today "Alvin C. Cruz" is literally a
`vendors` row, `V001`). That conflates two different BIR regimes:

- **Vendor payments** → creditable/expanded withholding (BIR 2307, 1601-EQ,
  supplier Alphalist), reported through the Purchases / expanded-withholding book.
- **Employee compensation** → withholding on compensation (BIR 1601-C, 2316),
  plus SSS / PhilHealth / Pag-IBIG, 13th-month, graduated tax tables.

The stated goal is a **foundation for real payroll**. Payroll is a large
subsystem, so it is decomposed into slices. **This spec covers only Slice 1: the
Employee master data model + CRUD.** It deliberately does *not* build payroll
posting, tax tables, or BIR compensation reports.

The literal question that started this ("can the vendor dropdown contain both
vendors and employees?") is answered **No** by this design: employees will get
their own payroll posting path in a later slice, rather than overloading the
`AccountsPayable.vendor_id` picker. Rationale is in "Rejected: combined payee
dropdown" below.

## Goal (this slice)

Add an Employee master to CAS: a branch-scoped, opt-in module with a model rich
enough that later payroll slices need **no identity migration**, plus standard
CRUD UI following existing CAS master-data conventions (vendors as the template).

## Scope

### In scope
- `Employee` model (`app/employees/models.py`), fields per "Data model" below.
- New `app/employees/` blueprint mirroring `app/vendors/` structure.
- CRUD: list / create / edit / Active-Inactive toggle.
- `employee_no` auto-generation (`EMP-####`), editable.
- Registration as an **opt-in module** in `MODULE_REGISTRY`.
- Hand-written Alembic migration (batch ops), verified on a real-DB copy.
- Full TDD test coverage incl. audit-log assertions.

### Out of scope (later slices — do NOT build here)
- Payroll / salary voucher and its GL posting (Salaries expense, WHT-Compensation
  payable, statutory payables).
- Compensation-withholding tax tables (TRAIN graduated).
- Statutory contribution tables (SSS / PhilHealth / Pag-IBIG, employee + employer).
- Payslips, 13th-month, de-minimis benefits.
- BIR 1601-C / 2316 / Alphalist of compensation.
- **Any change to the APV vendor dropdown.** Salary stays a manual APV for now.

## Data model — `Employee`

`__tablename__ = 'employees'`. All columns nullable unless noted.

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
| | `position` | String(120) | **Free-form HR job title.** See non-derivation rule. |
| Scope | `branch_id` | Integer FK `branches.id`, **NOT NULL**, indexed | branch-scoping rule |
| Tax | `tax_status_code` | String(10) | e.g. S, ME, ME1 … |
| | `qualified_dependents` | Integer, default 0 | |
| | `is_minimum_wage` | Boolean, default False | |
| Compensation | `pay_basis` | String(20) | monthly / daily |
| | `basic_rate` | Numeric(12,2) | |
| | `pay_frequency` | String(20) | monthly / semi-monthly |
| Link/status | `user_id` | Integer FK `users.id`, **nullable**, indexed | optional identity link |
| | `is_active` | Boolean, default True, NOT NULL | |
| Audit | `created_at`, `updated_at` | DateTime (PH time) | match sibling models |

Helpers: `full_name` property (`"first middle last"`, collapse blanks),
`to_dict()` returning loaded **columns only** (no lazy relationship reads — the
cache-detached trap), and a `branch` relationship (matching how vendors relate).

### Non-derivation rule (position vs. user role)
`User.role` (admin / accountant / staff / viewer) is **application authorization**;
`Employee.position` is an **HR job title**. They are orthogonal — the same person
can be an `admin` user whose position is "Managing Partner." `position` is a plain
text field, **never** a dropdown of user types and **never** derived from or synced
with `User.role`. The optional `user_id` link is **pure identity mapping** ("this
employee is also this login") and carries no role/position meaning.

### Why the optional `user_id` link
- Enables self-service payslips / 2316 in a later slice (a logged-in user sees only
  their own records).
- Enables segregation-of-duties checks (an employee-user can't approve their own
  payroll run).
- Nullable because not every employee has a login and not every user is an employee.
  One nullable FK now avoids a migration later.

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

Registration (both are explicit lists in `create_app` — must be edited manually):
1. Import `Employee` in the model-import block (for migration autodetect).
2. Register the `employees` blueprint.
3. Add an **opt-in** entry to `MODULE_REGISTRY` so instances that don't need payroll
   stay clean; gate views with the module-access mechanism and show the sidebar
   link only when the module is enabled.

`generate_next_employee_no()` mirrors `generate_next_vendor_code()` exactly:
sequence by the numeric suffix of `EMP%` codes (not lexicographic), format
`f'EMP-{n:04d}'` (4-wide, still increments correctly past 9999).

## UI / UX

- **List page** (`list.html`): table of employees (no, name, position, branch,
  status). Top launch button **"Create Employee"** (master-data verb). **No
  empty-state CTA** — plain "No employees found." only. Active/Inactive via the
  shared `status_toggle()` macro + `initStatusToggle()`; badges reuse global
  `.badge-active` / `.badge-inactive`.
- **Form page** (`form.html`): grouped sections (Identity, Gov IDs, Employment,
  Tax, Compensation, Link). Submit button **"Create"** / **"Update"**. Branch
  picker and any code-style pickers use `initSearchSelect` (Choices.js) with the
  `": "` separator. Optional User link is a search-select of active users
  (code+name style), blank allowed. Design tokens only, responsive.
- **Delete**: explicit pre-check before delete (SQLite FK-enforcement is off
  app-wide) — block if the employee is referenced by any future payroll record;
  for this slice there are no such references yet, so the guard is a forward-safe
  no-op that must still be written (and tested) so the child slices can rely on it.

## Numbering

`employee_no` auto-generated `EMP-####` (zero-padded, 4-wide), pre-filled on the
create form and **editable** (user can type a specific value). Uniqueness enforced
at the DB (unique index) and validated in the form.

## Audit & conventions

- Every create / update / delete / toggle calls `log_create` / `log_update` /
  `log_delete` (`app/audit/utils.py`); CRUD tests assert the audit entry (action,
  record ref, actor) per the CAS non-negotiable.
- PH-time helpers for all timestamps (`ph_now`), never naive `datetime.now()`.
- SQLAlchemy 2.0 spellings only (`db.session.get`, `db.get_or_404`).
- Model change requires explicit user approval before the model file is written /
  migrated — this spec + the plan serve as that proposal; sign-off gates coding.

## Testing (TDD)

Write tests first, then implement. Coverage:
- **Model:** unique `employee_no`; NOT-NULL `branch_id`; nullable `user_id`;
  `is_active` default; `full_name` property; `to_dict()` reads columns only.
- **Numbering:** `generate_next_employee_no()` sequences by numeric suffix,
  survives past 9999, skips non-conforming codes.
- **Views/CRUD:** create, edit, list, toggle status; audit-log assertion on each
  write; branch scoping (a user sees/creates only within accessible branches).
- **Delete guard:** delete blocked when referenced (forward-safe test using a stub
  reference), allowed otherwise.
- **Module gating:** views 404 / sidebar link hidden when the module is disabled.
- **Migration:** run `flask db upgrade` on a **copy of a real `cas.db`** and assert
  the `employees` table + unique index + NOT-NULL `branch_id` exist (a conftest
  `create_all()` unit test alone does not prove the migration — batch-mode gotcha).

## Rejected alternatives

### Combined payee dropdown (vendors + employees in the APV picker)
Technically feasible via a polymorphic payee (`payee_type` + `payee_id`), but
rejected because:
1. `AccountsPayable.vendor_id` is `NOT NULL` FK — a polymorphic change has blast
   radius across AP aging, the BIR purchases / expanded-withholding book, exports,
   and `to_dict` (all "done" modules).
2. Employees in the vendor list **leak into vendor reports** (AP aging, supplier
   Alphalist, expanded WHT) — the exact BIR-separation problem payroll should avoid.
3. Compensation withholding ≠ expanded withholding (different codes, different
   forms); the vendor "WHT default" mechanism is built for expanded WHT and would
   mislead on a salary.

Employees instead get a dedicated payroll posting path in a later slice.

## Payroll arc & future slices (not committed — for context only)

1. **Employee master** ← this spec.
2. Salary/payroll voucher + GL posting (Salaries expense / WHT-Compensation payable
   / statutory payables), separate from AP.
3. Compensation-WHT tables + statutory contribution tables (the calc engine).
4. Payslips, 13th-month, de-minimis.
5. BIR compensation reports (1601-C, 2316, Alphalist).

Each is its own spec → plan → build cycle.
