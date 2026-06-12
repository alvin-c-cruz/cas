# Run 2 — Vendor & AP Voucher Test Plan Design

## Goal

Manual browser test run covering: user registration and role-based login checks, vendor CRUD, AP voucher CRUD (with VAT, WT, and attachments), dashboard payables impact, and audit trail verification. Single branch, four users.

## Prerequisites — Code Fix Required

The vendor and AP voucher views currently use `accountant_or_admin_required` on all write operations. Staff permissions must be updated **before this run executes**:

| Operation | Current | Required |
|-----------|---------|----------|
| Vendor: create, edit, deactivate | accountant/admin | **staff/accountant/admin** |
| Vendor: delete | accountant/admin | accountant/admin (unchanged) |
| AP Voucher: create draft, edit draft, void draft | accountant/admin | **staff/accountant/admin** |
| AP Voucher: post, cancel | accountant/admin | accountant/admin (unchanged) |

Implementation: add `'staff'` to the role check on the above Tier 1 routes. Keep Tier 2 routes as-is. This may require a new decorator or inline guards — implementer's choice.

---

## Users

| Username | Role | Password | Source |
|----------|------|----------|--------|
| `admin` | Administrator | existing | Existing |
| `testaccountant` | Accountant | `TestAcc!Pass123` | Register fresh |
| `teststaff` | Staff | `TestStf!Pass123` | Register fresh |
| `testviewer` | Viewer | `TestVwr!Pass123` | Register fresh |

Emails to pre-approve: `testaccountant@testcas.com`, `teststaff@testcas.com`, `testviewer@testcas.com`

---

## Test Data

| Item | Value |
|------|-------|
| Primary vendor code | `V-TEST` |
| Primary vendor name | `Test Vendor Co.` |
| Throwaway vendor code | `V-DEL` |
| Throwaway vendor name | `Delete Me Corp.` |
| Bill amount | ₱11,200 VAT-inclusive |
| VAT rate | 12% (VAT = ₱1,200, net = ₱10,000) |
| VAT category | First available from seed data |
| EWT code | First available from seed data |
| Expense account | First available leaf account under Expenses in COA |
| Vendor invoice # | `INV-TEST-001` |
| Vendor invoice date | Same as bill date |
| Void reason | `Voided for testing purposes - Run 2` |
| Cancel reason | `Cancelled for testing purposes - Run 2` |

---

## Permission Model (Two Tiers)

**Tier 1 — Viewer blocked; Staff executes:**
- Create vendor, edit vendor, deactivate vendor
- Create AP draft, edit AP draft, upload attachment, void AP draft

**Tier 2 — Viewer + Staff blocked; Accountant executes:**
- Delete vendor
- Post AP voucher, cancel AP voucher

**Read access:** All authenticated users (viewer, staff, accountant, admin) can view lists and detail pages for vendors and AP vouchers.

---

## Write-Attempt Pattern

For every **Tier 1** write operation the sequence is:
1. Log in as testviewer → attempt → verify blocked with flash error
2. Log out → log in as teststaff → execute → verify success

For every **Tier 2** write operation the sequence is:
1. Log in as testviewer → attempt → verify blocked
2. Log out → log in as teststaff → attempt → verify blocked
3. Log out → log in as testaccountant → execute → verify success

---

## Section U — Users

**Purpose:** Register all three test users, promote roles, verify each user's dashboard and nav reflects their role correctly.

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| U-01 | admin | Pre-approve `testaccountant@testcas.com`, `teststaff@testcas.com`, `testviewer@testcas.com` via Approved Emails | All 3 appear as Available in the list |
| U-02 | — | Register `testaccountant` (email: testaccountant@testcas.com, password: TestAcc!Pass123) | Redirected to /login, flash "pending admin approval" |
| U-03 | — | Register `teststaff` (email: teststaff@testcas.com, password: TestStf!Pass123) | Redirected to /login, flash "pending admin approval" |
| U-04 | — | Register `testviewer` (email: testviewer@testcas.com, password: TestVwr!Pass123) | Redirected to /login, flash "pending admin approval" |
| U-05 | admin | Edit testaccountant → Activate + set role = Accountant | Flash "updated successfully" |
| U-06 | admin | Edit teststaff → Activate + set role = Staff | Flash "updated successfully" |
| U-07 | admin | Edit testviewer → Activate (role stays Viewer) | Flash "updated successfully" |
| U-08 | testviewer | Log in → Dashboard | Welcome flash. No `+ New` button. No Action Items link. No Admin section. No VAT Categories in nav. |
| U-09 | testviewer | Log out | Flash "logged out successfully" |
| U-10 | teststaff | Log in → Dashboard | Welcome flash. `+ New` button visible. Action Items visible. No Admin section. No VAT Categories in nav. |
| U-11 | teststaff | Log out | Flash "logged out successfully" |
| U-12 | testaccountant | Log in → Dashboard | Welcome flash. `+ New` button. Action Items. VAT Categories visible. Audit Log visible. No User Management. |
| U-13 | testaccountant | Log out | Flash "logged out successfully" |
| U-14 | admin | Log in → Dashboard | Full nav: User Management, Approved Emails, all Admin items visible. |

---

## Section V — Vendor

**Purpose:** Full vendor lifecycle. Staff creates and edits; accountant deletes. Role blocks verified at each write tier.

### Read

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-01 | testviewer | Navigate to /vendors | List renders. No "+ Create Vendor" button visible. |
| V-02 | teststaff | Navigate to /vendors | List renders. "+ Create Vendor" button visible. |

### Create (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-03 | testviewer | Navigate to /vendors/create | Blocked — flash error, redirected. |
| V-04 | teststaff | Create vendor: code=V-TEST, name=Test Vendor Co., payment_terms=Net 30, select any available VAT category and EWT code | Flash "Vendor created". V-TEST appears in list as Active. |
| V-05 | teststaff | Create vendor: code=V-DEL, name=Delete Me Corp. | Flash "Vendor created". V-DEL appears in list. |

### Read Detail

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-06 | testviewer | View V-TEST detail | All fields visible: code, name, payment terms, VAT category, WHT codes. No Edit/Delete buttons. |

### Edit (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-07 | testviewer | Navigate to /vendors/\<id\>/edit (V-TEST) | Blocked — flash error, redirected. |
| V-08 | teststaff | Edit V-TEST: add phone=09171234567, address=123 Test St. | Flash "Vendor updated". Changes visible in detail. |

### Deactivate (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-09 | testviewer | Edit V-TEST → uncheck Active | Blocked — flash error, redirected. |
| V-10 | teststaff | Edit V-TEST → uncheck Active → save | Flash "Vendor updated". Status shows Inactive. |
| V-11 | teststaff | Edit V-TEST → check Active → save | Flash "Vendor updated". Status shows Active. *(Required — vendor must be active for AP section.)* |

### Delete (Tier 2)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| V-12 | testviewer | Delete V-DEL | Blocked — flash error, redirected. |
| V-13 | teststaff | Delete V-DEL | Blocked — flash error, redirected. |
| V-14 | testaccountant | Delete V-DEL | Flash "Vendor deleted". V-DEL no longer in list. Audit entry: module=vendor, action=delete. |

---

## Section AP — AP Voucher

**Purpose:** Full AP voucher lifecycle. Staff creates draft, edits, uploads attachment, voids a second draft. Accountant posts the first bill and cancels it. Role blocks verified at each tier.

### Read

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-01 | testviewer | Navigate to /purchase-bills | List renders. No "+ New AP Voucher" button visible. |
| AP-02 | teststaff | Navigate to /purchase-bills | List renders. "+ New AP Voucher" button visible. |

### Create Draft (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-03 | testviewer | Navigate to /purchase-bills/create | Blocked — flash error, redirected. |
| AP-04 | teststaff | Create draft: vendor=Test Vendor Co., bill_date=today, due_date=today+30, one line item: description="Test Expense", amount=₱11,200, VAT category=first available (12%), expense account=first available, EWT code=first available. Leave vendor invoice # blank. | Bill created as draft. Bill number AP-YYYY-MM-XXXX assigned. Subtotal=₱11,200, VAT=₱1,200, WT calculated, Total=subtotal−WT. Status=draft. |

### Read Draft Detail (all roles)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-05 | testviewer | View draft bill detail | Status=draft visible. JE preview section shows debit/credit lines. No Post, Void, or Edit buttons visible for viewer. |
| AP-06 | teststaff | View draft bill detail | Status=draft. Edit and Void buttons visible. No Post button (Tier 2). |
| AP-07 | testaccountant | View draft bill detail | Status=draft. Edit, Post, and Void buttons visible. |

### Edit Draft (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-08 | testviewer | Navigate to /purchase-bills/\<id\>/edit | Blocked — flash error, redirected. |
| AP-09 | teststaff | Edit draft: add vendor_invoice_number=INV-TEST-001, vendor_invoice_date=today, add reference=PO-2026-001 | Flash "APV updated". Changes visible in detail. JE preview refreshed. |

### Upload Attachment (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-10 | testviewer | Attempt to upload attachment on draft | Blocked — flash error or 403. |
| AP-11 | teststaff | Upload one PDF or image file to draft bill | File appears in attachments section with filename, size. Audit entry: module=purchase_bill_attachment, action=create. |

### Download Attachment (all roles)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-12 | testviewer | Download attachment from draft bill | File downloads successfully. |
| AP-13 | teststaff | Download attachment | File downloads successfully. |

### Post (Tier 2)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-14 | testviewer | Attempt to post draft bill | Blocked — flash error, redirected. |
| AP-15 | teststaff | Attempt to post draft bill | Blocked — flash error, redirected. |
| AP-16 | testaccountant | Post bill | Flash "APV posted". Status=posted. Post button disappears. Edit/Void buttons disappear. Cancel button appears. Audit entry: module=purchase_bill, action=post. |

### Read Posted Detail (all roles)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-17 | testviewer | View posted bill detail | Status=posted. Attachment still visible and downloadable. No edit/cancel buttons for viewer. |
| AP-18 | teststaff | View posted bill detail | Status=posted. No edit/void/cancel buttons (all Tier 2 or inapplicable). |

### Second Draft — for Void Test (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-19 | teststaff | Create second draft: same vendor, same line item structure (₱11,200), no vendor invoice # | Draft created. New bill number (next in sequence). |

### Void Draft (Tier 1)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-20 | testviewer | Attempt to void second draft | Blocked — flash error, redirected. |
| AP-21 | teststaff | Void second draft: enter reason "Voided for testing purposes - Run 2" (32 chars, ≥10 required), set void date=today | Flash "APV voided". Status=voided. Attachment (if any) deleted. Audit entry: module=purchase_bill, action=void, reason in notes. |

### Cancel Posted Bill (Tier 2)

| # | Actor | Action | Expected |
|---|-------|--------|----------|
| AP-22 | testviewer | Attempt to cancel first posted bill | Blocked — flash error, redirected. |
| AP-23 | teststaff | Attempt to cancel first posted bill | Blocked — flash error, redirected. |
| AP-24 | testaccountant | Cancel first posted bill: reason "Cancelled for testing purposes - Run 2", reversal date=today | Flash "APV cancelled". Status=cancelled. Reversal JE created (posted). Audit entry: module=purchase_bill, action=cancel, reason in notes. |

---

## Section DB — Dashboard

**Purpose:** Verify the dashboard payables stats reflect AP voucher state changes at each key transition.

| # | When | Actor | Check | Expected |
|---|------|-------|-------|----------|
| DB-01 | After AP-04 (draft created) | testaccountant | /dashboard → Accounts Payable card | payables_total and payables_count **unchanged** from baseline. Draft bills do not count. |
| DB-02 | After AP-16 (posted) | testaccountant | /dashboard → Accounts Payable card | payables_total **increases** by bill's total_amount (₱11,200 − WT). payables_count **increases by 1**. |
| DB-03 | After AP-24 (cancelled) | testaccountant | /dashboard → Accounts Payable card | payables_total and payables_count **reset** (cancelled bill removed from outstanding payables). |

---

## Section AT — Audit Trail

**Purpose:** Spot-check seven key audit entries written during the run. All checks performed by testaccountant (has Audit Log access).

| # | Navigate to | Filter | Expected Entry |
|---|-------------|--------|----------------|
| AT-01 | /audit-log | module=vendor, action=create | record_identifier="V-TEST - Test Vendor Co.", user=teststaff, new_values contains code + name + is_active=true |
| AT-02 | /audit-log | module=vendor, action=update | record_identifier="V-TEST - Test Vendor Co.", user=teststaff, old_values and new_values show changed fields only (phone, address) |
| AT-03 | /audit-log | module=vendor, action=delete | record_identifier="V-DEL - Delete Me Corp.", user=testaccountant, old_values contains full vendor snapshot |
| AT-04 | /audit-log | module=purchase_bill, action=create | record_identifier contains AP bill number + vendor name, user=teststaff, new_values contains subtotal, vat_amount, total_amount, status=draft |
| AT-05 | /audit-log | module=purchase_bill, action=post | Same bill number, user=testaccountant |
| AT-06 | /audit-log | module=purchase_bill, action=void | Second bill number, user=teststaff, notes contains void reason |
| AT-07 | /audit-log | module=purchase_bill, action=cancel | First bill number, user=testaccountant, notes contains cancel reason |

---

## Cleanup (end of run)

| Step | Actor | Action |
|------|-------|--------|
| C-01 | testaccountant | Delete V-TEST vendor (Test Vendor Co.) |
| C-02 | admin | Delete testaccountant user |
| C-03 | admin | Delete teststaff user |
| C-04 | admin | Delete testviewer user |
| C-05 | admin | Verify Approved Emails page — 3 emails show as Used with no linked user (expected; no action needed) |

---

## Scenario Count

| Section | Scenarios |
|---------|-----------|
| U — Users | 14 |
| V — Vendor | 14 |
| AP — AP Voucher | 24 |
| DB — Dashboard | 3 |
| AT — Audit Trail | 7 |
| Cleanup | 5 |
| **Total** | **67** |

---

## Out of Scope

- VAT category and WT code master data changes (no add/edit/delete)
- Cross-branch testing
- Sales invoices, receipts, journal entries
- AP voucher payments (amount_paid tracking)
- Attachment edge cases (wrong file type, file size limit)
- AP voucher export to Excel/CSV
- Closed period date validation
