# Spec: flask seed-minimal + Admin Self-Approval

**Date:** 2026-06-12
**Status:** Approved

## Context

For client testing on PythonAnywhere, we need a clean database that is pre-configured enough for a client to immediately enter an AP Voucher without any setup. The existing `flask seed-db` seeds a full 173-account COA plus generic VAT/WHT codes — too much for a demo state. We need a `flask seed-minimal` command that seeds only the minimum required master data using the real codes/names signed off during Run 1.

A secondary issue: with only `admin` in a fresh database, admin submits a change request → goes pending → cannot self-approve (blocked by current rule) → stuck with no one to approve. Fix: admin is superuser and can always approve any change request, including their own.

---

## Part 1: `flask seed-minimal`

### Command

```bash
flask seed-minimal
```

Registered in `app/__init__.py` alongside the existing `seed-db` command. Calls `seed_minimal()` from `app/seeds/seed_data.py`.

### Seed contents (in creation order)

**Admin user**
- username: `admin`, role: `admin`, `is_active=True`
- Password: the standard dev/demo password (same as `seed-db`)

**Branch**
- Code: `MAIN`, Name: `Main Branch`
- Admin assigned to this branch via `UserBranch`

**App settings** (4 keys, matching existing seed keys)
- `company_name`: `""` (empty — client fills in)
- `company_tin`: `""`
- `company_address`: `""`
- `fiscal_year_start`: `"01"`

**Chart of Accounts** (6 accounts, direct DB insert — no change request)

| Code | Title | Type | Parent |
|------|-------|------|--------|
| 10500 | Input VAT | Asset | — (group) |
| 10501 | Input VAT - Capital Goods | Asset | 10500 |
| 20101 | Accounts Payable - Trade | Liability | — |
| 20300 | Withholding Tax Payable | Liability | — (group) |
| 20301 | Withholding Tax Payable - Expanded | Liability | 20300 |
| 60101 | Office Supplies Expense | Expense | — |

Groups (10500, 20300) have no `parent_id`. Children reference their parent by code, resolved at seed time.

**VAT Categories** (4, direct DB insert — no change request)

| Code | Name | Rate % | Input VAT Account |
|------|------|--------|-------------------|
| V12 | VAT 12% | 12.00 | 10501 |
| V0 | VAT Zero-Rated | 0.00 | — |
| VEX | VAT Exempt | 0.00 | — |
| INV | Invalid | 0.00 | — |

`V12.input_vat_account_id` is resolved after accounts are created by querying `Account.query.filter_by(code='10501').first().id`.

**WHT Codes** (3, direct DB insert — no change request)

| Code | Name | Rate % |
|------|------|--------|
| WC158 | Withholding Tax - Goods | 1.00 |
| WC160 | Withholding Tax - Services | 2.00 |
| WC100 | Withholding Tax - Rentals | 5.00 |

### Reset procedure (PythonAnywhere)

```bash
rm -f ~/cas/instance/cas.db
flask db upgrade
flask seed-minimal
```

---

## Part 2: Admin self-approval

### Rule

`admin` role can approve **any** change request, including their own, at all times. Accountant self-approval logic is unchanged.

### Files to update

The three modules use different patterns — each needs a targeted fix:

**1. `app/accounts/approval_models.py` — `AccountChangeRequest.can_be_approved_by()`**

Prepend an admin short-circuit before the existing count-based logic:

```python
def can_be_approved_by(self, username):
    from app.users.models import User
    reviewer = User.query.filter_by(username=username).first()
    if reviewer and reviewer.role == 'admin':
        return True  # admin always approved, including own requests
    # ... existing accountant logic unchanged ...
```

**2. `app/vat_categories/views.py` — `review_change_request()` (line ~486)**

Change the hard self-block to exempt admins:

```python
# Before:
if change_request.requested_by_id == current_user.id:
# After:
if change_request.requested_by_id == current_user.id and current_user.role != 'admin':
```

**3. `app/withholding_tax/views.py` — `review_change_request()` (line ~446)**

Same one-line change as VAT categories.

Accountant self-approval logic is unchanged in all three modules.

---

## Verification

1. `flask seed-minimal` on a fresh DB → login as admin → dashboard shows empty state → all 6 accounts, 4 VAT categories, 3 WHT codes present in their respective list pages
2. Enter an APV with vendor, V12 VAT, WC158 WHT, account 60101 → save draft → JE preview shows correct accounts → post (with invoice # and date) → posts successfully
3. Admin submits a COA change request → it goes to pending → admin can approve their own request from Action Items → account appears in COA
4. With an accountant also present: accountant submits → still goes pending; accountant still cannot self-approve their own when another accountant exists (regression)
