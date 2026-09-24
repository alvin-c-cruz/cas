# CV employee payee — design

**Date:** 2026-09-24
**Status:** implemented 2026-09-24 (commits f1ff706b..b04ddbb4 + this task); see the plan beside this file
**Owner's words:** "I cant access the employee names from CV extra. they should be available for both branches."

## The problem, as found

The report says branch. The data says otherwise.

A Cash Disbursement Voucher (CV/CDV) has no employee payee concept at all. `CashDisbursementVoucher.vendor_id`
is NOT NULL and the only picker on the form lists `Vendor` rows; `open_bills` filters payable APVs by
`AccountsPayable.vendor_id`. Meanwhile the APV has been polymorphic since 2026-07-08 (`d9bebfed48f3`):
`payee_type` in (`vendor`, `employee`), `payee_id`, `vendor_id` nullable and NULL for an employee.

On philgen production there are nine employee-payee APVs (`payee_type='employee'`, `vendor_id NULL` —
0001E TANG, 0002E KIOK, 0003E REDULFIN, 0004E ISHMAEL, …). No CV in any branch can pay them, because no
CV can name an employee. That is what the owner met in CV EXTRA; it would have been identical in CORP.

The APV's employee picker is already scoped to the branches the user can **reach** (set membership, not
the selected branch — `_employee_payee_query`, BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED), so an
admin sees every employee from either branch there. "Available for both branches" therefore needs no
new branch rule; it needs the CV to have a payee at all.

## Decisions taken with the owner

1. **Scope: Sections A and B both.** Settle an employee's posted APVs (Section A) and pay an employee
   directly for an expense with no APV — cash advance, reimbursement (Section B). Same reach the APV has.
2. **Tax on Section B employee lines: both VAT and WHT, like a vendor.** VAT category per line as now.
   WHT is offered too; since an employee has no assigned WHT codes (a vendor does), an employee line
   offers **every active WHT code**.
3. **Approach A — polymorphic payee on the CV, mirroring the APV.** Rejected: B, a shadow Vendor per
   employee (two master records for one person, TIN/address drift, vendor list and 2307 polluted, and a
   person would be an *employee* on the APV and a *vendor* on the CV that pays it); C, a separate
   employee-disbursement document (second numbering series and printout for one physical CV pad).

## Design

### 1. Data model and migration

`cash_disbursement_vouchers` gains:

| column | type | constraint |
|---|---|---|
| `payee_type` | `String(20)` | NOT NULL, `server_default='vendor'`, indexed |
| `payee_id` | `Integer` | NOT NULL, `server_default='0'` |

`vendor_id` becomes **nullable** (NULL for an employee payee). `vendor_name` (NOT NULL) and `vendor_tin`
stay and keep their names: they are the historical snapshot for **either** kind of payee, exactly as on
`AccountsPayable`. Renaming them would touch every template and report for no behavioural gain.

`CashDisbursementVoucher` gains two properties copied from `AccountsPayable`:

- `payee` — the `Vendor` or `Employee` row (or `None`), resolved from `payee_type`/`payee_id`.
- `payee_display_name` — `full_name` for an employee, `name` for a vendor, `vendor_name` snapshot when
  the row is gone.

`to_dict()` carries `payee_type` and `payee_id`.

**Migration `cdvpay_0001`** (hand-written batch; no inline FK; conventions in the workspace CLAUDE.md):

```python
with op.batch_alter_table('cash_disbursement_vouchers', schema=None) as batch_op:
    batch_op.add_column(sa.Column('payee_type', sa.String(length=20), nullable=False, server_default='vendor'))
    batch_op.add_column(sa.Column('payee_id', sa.Integer(), nullable=False, server_default='0'))
    batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)
    batch_op.create_index('ix_cash_disbursement_vouchers_payee_type', ['payee_type'], unique=False)
op.execute("UPDATE cash_disbursement_vouchers SET payee_type='vendor', payee_id=vendor_id "
           "WHERE payee_id=0 OR payee_id IS NULL")
```

Every existing CV is a vendor payment, so the backfill changes no meaning. Downgrade reverses the four
steps; it must refuse (raise) if any row has `payee_type='employee'`, because `vendor_id NOT NULL` cannot
be restored over them. The check-serial partial unique index `uq_cdv_cash_account_check_number` keys on
`cash_account_id` and is untouched. Rehearse on a copy of philgen's books (`tools/verify_r08_migration.py`
is the worked example) before it ships.

### 2. One payee rule for both vouchers

Three helpers exist today in `app/accounts_payable/views.py` and move, unchanged in behaviour, to a new
`app/common/payee.py`, imported by both the APV and the CV:

- `parse_payee(value)` — `'vendor:12' | 'employee:3'` → `(payee_type, payee_id)` or `(None, None)`.
- `employee_payee_query()` — active employees whose `branch_id` is in the user's **accessible** branches.
- `resolve_payee(payee_type, payee_id)` — the row, or `None` when the employee's branch is unreachable
  (the caller's existing "Selected payee not found." path handles `None`; nothing new is disclosed).

The CV form's vendor `<select>` (`form.vendor_id`, `id="vendor_id"`) becomes the APV's `payee` select:
one searchable Choices.js list, vendors first as `CODE : NAME [Vendor]`, then employees as
`NO : FULL NAME [Employee]`, employees ordered by `employee_no`. `CashDisbursementForm.vendor_id` is
replaced by a `payee` `StringField`; validation of the parsed value happens in the view via
`resolve_payee`, as the APV does.

The view stores, for either kind: `payee_type`, `payee_id`, `vendor_id` (vendor only, else `None`),
`vendor_name` (`name` / `full_name`), `vendor_tin` (`tin` on both models).

### 3. Section A — settling APVs

`open_bills` filters `AccountsPayable.payee_type == payee_type AND AccountsPayable.payee_id == payee_id`
(plus the existing branch, status and balance filters) instead of `vendor_id`. Its request parameter
changes from `vendor_id` to `payee=<type:id>`. Settlement posting is untouched: it reads each APV's own
resolved AP-trade account, which is payee-agnostic.

### 4. Section B — direct expense lines

The form today calls `/vendors/<id>/defaults` for three things: the vendor's WHT codes, its last cash
account and its last expense account. A new endpoint serves both kinds with one shape:

`GET /cash-disbursements/payee-defaults?payee=<type:id>` →
`{"withholding_taxes": [...], "last_cash_account_id": …, "last_expense_account_id": …}`

- vendor: delegates to the existing vendor logic (assigned WHT codes; last CV's accounts).
- employee: `withholding_taxes` = **all** active WHT codes (decision 2); the two "last" values come from
  the employee's most recent posted CV, else `null`.

The form's WHT selects are rebuilt from that list exactly as now. The posting seam
(`app/posting/buckets.py`) never sees the payee and is not touched.

### 5. Posting, printouts, check

- JE description stays `CD <cdv_number> — <vendor_name>`; for an employee that is the full name.
- Check overlay (`_build_check_values`): payee = `vendor.check_payee_name` when the payee is a vendor and
  it is set (2026-09-23 rule), else `vendor_name` — which for an employee is the full name. Employees
  have no check-payee alias.
- Pre-printed voucher: `vendor_name` ("Pay To") prints the snapshot; `check_payee` is `''` for an
  employee; `deposit_account` is `''` (no bank details on an employee — consistent with the 2026-09-24
  "blank when none" rule). Detail page and standard print: the "Deposit to" block does not render.
- Every `cdv.vendor.` / `cdv.vendor_id` read in `app/cash_disbursements/` is enumerated in the plan and
  either made payee-aware or guarded for `None`. The 2307/withholding side reads `vendor_tin`, which is
  populated for both.

### 6. Lists, filters, reports, exports

- CV list: the "vendor" filter becomes a payee filter offering both kinds (`vendor:12` / `employee:3`);
  the search box already matches `vendor_name`.
- Export (`_cdv_export_data`): add `payee_type`.
- `app/reports/vat_lines.py` already guards `cdv.vendor is None` (address falls back to `None`); an
  employee CV's VAT-bearing line still appears in the purchases relief with the employee's TIN, which is
  correct for a liquidated purchase claiming input VAT.
- Vendor-side lookups that filter `CashDisbursementVoucher.vendor_id == x` (`app/vendors/utils.py`,
  vendor detail "recent payments") are vendor-only by intent and stay as they are.
- Audit: `log_create`/`log_update` field lists gain `payee_type`, `payee_id`.

### 7. Out of scope

- Employee bank details / deposit block for employees.
- Per-employee WHT code assignment (decision 2 offers all codes instead).
- Petty cash and payroll disbursement paths (they do not go through the CV form).
- Any change to the APV.

## Tests

All through the real HTTP routes, per the workspace rules (audit verified on create/update).

1. **Migration** — rehearsed against a copy of philgen's database: upgrade, every pre-existing CV reads
   `payee_type='vendor'` with `payee_id == vendor_id`, integrity check clean; downgrade with no employee
   rows reverses cleanly; downgrade with an employee row refuses.
2. **Picker** — from a session in branch EXTRA, an admin's CV form offers a CORP employee; a staff user
   assigned only EXTRA does not see a CORP employee and a hand-posted `payee=employee:<corp id>` is
   refused with "Selected payee not found." (mirrors `test_ap_employee_payee_branch_scope.py`).
3. **Section A** — an employee with two posted APVs: `open_bills?payee=employee:<id>` lists both and no
   vendor's; a CV settling one posts, the APV balance drops, the JE credits cash and debits AP-trade.
4. **Section B** — an employee CV with one VAT line and one WHT line posts; `payee-defaults` for the
   employee returns every active WHT code; for a vendor it returns the assigned subset (control).
5. **Check** — `print-check` for an employee CV prints the full name in the payee field.
6. **Printouts/detail** — no "Deposit to" block, `check_payee` empty, `Pay To` = full name.
7. **Vendor path unchanged** — the existing CDV suite (274 tests, all vendor payees) stays green; a
   vendor CV still stores `vendor_id`.
8. **Audit** — create and update logs carry `payee_type`/`payee_id` with real before/after values.
9. **Shared helpers** — `app/common/payee.py` unit tests; the APV tests that pinned the branch rule keep
   passing after the move.

## Deployment

Needs a migration on the server (`flask db upgrade` → `cdvpay_0001`), so the `deploy` runbook's backup
and integrity steps apply. No new dependencies. No data entry is required afterwards: existing CVs are
already vendor payments and the nine employee APVs become payable the moment the code is live.
