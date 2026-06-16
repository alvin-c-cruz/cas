# CAS Cash Disbursement Voucher (CDV) — Manual Test Plan

**System:** http://127.0.0.1:5000/  
**Date:** 2026-06-16  
**Tester:** _______________  
**Scope:** CDV list, create, edit, view, post, void, cancel, export, print, role access, audit log

---

## PHASE 0 — Pre-Test Setup

### 0.1 Route Map

| Route | Methods | Who can access |
|-------|---------|----------------|
| `/cash-disbursements` | GET | All logged-in roles |
| `/cash-disbursements/create` | GET, POST | Staff, Accountant, Admin |
| `/cash-disbursements/<id>` | GET | All logged-in roles |
| `/cash-disbursements/<id>/edit` | GET, POST | Staff, Accountant, Admin (draft only) |
| `/cash-disbursements/<id>/post` | POST | Accountant, Admin |
| `/cash-disbursements/<id>/void` | POST | Staff, Accountant, Admin (draft only) |
| `/cash-disbursements/<id>/cancel` | POST | Accountant, Admin (posted only) |
| `/cash-disbursements/<id>/print` | GET | All logged-in (gated by `cd_print_access` setting) |
| `/cash-disbursements/export/excel` | GET | All logged-in |
| `/cash-disbursements/export/csv` | GET | All logged-in |
| `/cash-disbursements/open-bills` | GET (JSON) | All logged-in (AJAX) |

### 0.2 Role Matrix

| Action | admin | accountant | staff | viewer |
|--------|-------|------------|-------|--------|
| View list | ✓ | ✓ | ✓ | ✓ |
| View detail | ✓ | ✓ | ✓ | ✓ |
| Create CDV | ✓ | ✓ | ✓ | ✗ |
| Edit draft CDV | ✓ | ✓ | ✓ | ✗ |
| Post CDV | ✓ | ✓ | ✗ | ✗ |
| Void draft CDV | ✓ | ✓ | ✓ | ✗ |
| Cancel posted CDV | ✓ | ✓ | ✗ | ✗ |
| Export Excel / CSV | ✓ | ✓ | ✓ | ✓ |
| Print CDV | ✓ | ✓ | ✓ | ✓ (gated) |

### 0.3 CDV Status Lifecycle

```
draft ──► posted ──► cancelled
  │
  └──► voided
```

- **Draft:** Created but not yet posted to the books. Can be edited or voided.
- **Posted:** Committed to the books. AP bills updated. Can only be cancelled.
- **Voided:** Discarded draft. Journal entry deleted. Terminal state.
- **Cancelled:** Reversal JE created. AP bill payments reversed. Terminal state.

### 0.4 Prerequisites — Master Data Required

Before testing CDVs, the following must exist in the database:

| # | Data | Where to create | Notes |
|---|------|-----------------|-------|
| P1 | At least one active **Vendor** | `/vendors/create` | Use: code=`V-CDV`, name=`CDV Test Vendor` |
| P2 | At least one **cash/bank Asset account** | COA | Use: code=`10101`, name=`Cash on Hand` (type=Asset) |
| P3 | At least one **Expense account** | COA | Use: code=`50001`, name=`Office Supplies` (type=Expense) |
| P4 | At least one active **VAT Category** | `/settings/vat-categories` | Use: code=`V12DG`, rate=12% |
| P5 | At least one active **WHT Code** | `/settings/withholding-tax` | Use: code=`WC158`, rate=2% |
| P6 | At least one **posted AP bill** for the test vendor | `/accounts-payable/create` | Amount: ₱11,200.00 — used for AP-line tests |
| P7 | AP/WHT GL accounts seeded | COA | `20101` Accounts Payable Trade, `20301` WHT Payable |

### 0.5 Setup Steps

| # | Step | Notes |
|---|------|-------|
| S1 | Start dev server: `python flask_app.py` | Port 5000 |
| S2 | Log in as `admin` | `admin` / `admin123` |
| S3 | Select **Main Branch** from the branch picker | Session must have a branch before any CDV route |
| S4 | Confirm P1–P7 prerequisites exist; create any that are missing | |
| S5 | Note the AP bill number from P6 (e.g., `AP-2026-06-0001`) | You'll select it during CDV create |

---

## PHASE 1 — Functional Testing

### 1.1 List View

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 1 | List page loads | GET `/cash-disbursements` | Page renders; table or empty-state shown; no error |
| 2 | CDV appears in list after create | Create a CDV (any method), return to list | New CDV number visible in list |
| 3 | Filter by status=draft | Append `?status=draft` | Only draft CDVs shown |
| 4 | Filter by status=posted | Append `?status=posted` | Only posted CDVs shown |
| 5 | Search by CDV number | Append `?q=CD-` | Matching CDVs shown |
| 6 | Filter by date range | Set `date_from` and `date_to` to today | Only today's CDVs shown |
| 7 | List is branch-scoped | Switch to a second branch (if available) | CDVs from original branch no longer visible |

### 1.2 Create CDV — Expense Lines Only

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 8 | Create form loads | GET `/cash-disbursements/create` | Form renders; CDV number pre-filled (format `CD-YYYY-MM-NNNN`); date defaults to today |
| 9 | Create with one expense line (no VAT, no WHT) | Vendor=`CDV Test Vendor`, cash account=`Cash on Hand`, add expense line: desc=`Office Supplies`, amount=₱1,000, no VAT, account=`Office Supplies` | CDV saved as draft; redirected to list or detail; CDV number visible |
| 10 | Verify draft JE was created | From CDV detail page, check JE preview section | JE lines shown; status=draft |
| 11 | Create with VAT (12%) | Expense line: amount=₱1,120, VAT=V12DG (12%) | VAT extracted: ₱120 VAT, ₱1,000 net; `total_vat` = ₱120 |
| 12 | Create with WHT | Expense line with WHT=WC158 (2%), amount=₱1,000 net | WHT applied to net; `total_wt` computed correctly |
| 13 | Create with VAT override | Check "Override VAT", enter ₱500 manually | `total_vat`=₱500; auto-calculation bypassed |
| 14 | Create with WHT override | Check "Override WHT", enter ₱200 manually | `total_wt`=₱200; auto-calculation bypassed |
| 15 | Create with check payment | Set payment_method=`Check`; fill check number, date, bank | All check fields saved; visible on detail page |
| 16 | Attempt create with no line items | Submit form with no expense lines and no AP lines | Form rejected or CDV has ₱0 total; note actual behavior |
| 17 | Required field missing — no vendor | Remove vendor selection and submit | Form validation error; CDV NOT created |
| 18 | Required field missing — no cash account | Remove cash account and submit | Form validation error; CDV NOT created |
| 19 | Audit log after create | Check audit log at `/audit-log` | Entry exists: module=`cash_disbursement`, action=`create` |

### 1.3 Create CDV — AP Lines Only

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 20 | Select a vendor — open bills appear | Pick `CDV Test Vendor` in vendor field | AJAX loads open AP bills for that vendor in the AP lines section |
| 21 | Apply full payment to an AP bill | Select AP bill `AP-2026-06-0001` (₱11,200), set amount_applied=₱11,200 | CDV saved; `total_ap_applied`=₱11,200 |
| 22 | Apply partial payment | Set amount_applied=₱5,000 on an ₱11,200 bill | CDV saved; `total_ap_applied`=₱5,000 |
| 23 | AP bill from different vendor does not appear | Switch vendor — AP bills from original vendor absent | Bills are vendor-scoped |

### 1.4 Create CDV — Mixed (AP + Expense Lines)

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 24 | Mixed: 1 AP line + 1 expense line | Select AP bill + add expense line | Both saved; `total_ap_applied` and `total_expense` both > 0 |
| 25 | Total amount = AP + Expense − WHT | Mixed CDV with WHT | Verify `total_amount` = `total_ap_applied` + `total_expense` − `total_wt` |

### 1.5 View CDV Detail

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 26 | Detail page loads | GET `/cash-disbursements/<id>` | CDV fields shown: number, date, vendor, payment method, totals |
| 27 | JE preview section visible | View draft CDV detail | Journal entry lines shown (debit/credit columns) |
| 28 | Status badge visible | View draft, posted, voided, cancelled CDVs | Badge shows correct status with appropriate colour |
| 29 | Print button — posted_only setting | `cd_print_access`=`posted_only` (default): view a draft CDV | Print button hidden |
| 30 | Print button — posted_only setting | View a posted CDV | Print button visible |
| 31 | Print button — draft_and_posted setting | Change `cd_print_access`=`draft_and_posted` in settings; view a draft CDV | Print button visible |

### 1.6 Edit CDV

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 32 | Edit form loads for draft CDV | GET `/cash-disbursements/<draft_id>/edit` | Form pre-filled with existing values |
| 33 | Edit notes field | Change notes text, submit | Updated notes shown on detail page |
| 34 | Edit replaces line items | Remove existing expense line, add two new ones | Old line gone; two new lines saved |
| 35 | Edit rebuilds JE | After edit, view JE preview on detail page | JE reflects updated line items |
| 36 | Audit log after edit | Check `/audit-log` | Entry: action=`update` for this CDV |
| 37 | Cannot edit a posted CDV | Navigate to `/cash-disbursements/<posted_id>/edit` | Blocked — redirect or error message; CDV unchanged |
| 38 | Cannot edit a voided CDV | Navigate to edit URL for voided CDV | Blocked |

### 1.7 Post CDV (Draft → Posted)

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 39 | Post a draft CDV | Click "Post" button on detail page | Status changes to `posted`; JE status = `posted`; posted_by visible |
| 40 | AP bill updates on post (full payment) | Post a CDV with amount_applied = full bill balance | AP bill status → `paid`; `balance`=₱0 |
| 41 | AP bill updates on post (partial payment) | Post a CDV with partial amount_applied | AP bill status → `partially_paid`; `balance` reduced |
| 42 | Audit log after post | Check `/audit-log` | Entry: action=`post` for this CDV |
| 43 | Cannot post an already-posted CDV | Try to post a posted CDV | No change; error flash or button absent |
| 44 | Staff cannot post | Log in as staff, navigate to a draft CDV detail | "Post" button absent or attempt blocked |

### 1.8 Void CDV (Draft → Voided)

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 45 | Void a draft CDV | Click "Void" on detail page; enter reason (≥10 chars); confirm | Status → `voided`; void reason stored; JE deleted |
| 46 | Void reason too short | Enter fewer than 10 characters | Form rejected; CDV stays `draft`; error message shown |
| 47 | Void reason stored | After voiding, view CDV detail | Void reason visible on detail page |
| 48 | JE deleted after void | Check JE preview section after void | JE no longer linked / section gone |
| 49 | Audit log after void | Check `/audit-log` | Entry: action=`void` for this CDV |
| 50 | Cannot void a posted CDV | "Void" button should be absent on posted CDV detail | Voiding blocked |

### 1.9 Cancel CDV (Posted → Cancelled)

| # | Test Case | Input | Expected |
|---|-----------|-------|----------|
| 51 | Cancel a posted CDV | Click "Cancel" on posted CDV detail; enter reason (≥10 chars) + reversal date; confirm | Status → `cancelled`; reversal JE created and posted |
| 52 | Reversal JE exists | After cancel, check JE list or audit | Reversal JE visible; `entry_type`=`reversal`, `is_reversing`=True, `status`=`posted` |
| 53 | AP bill payments reversed | After cancel, view the AP bill that was paid | `amount_paid` reduced; `balance` restored; status → `posted` or `partially_paid` |
| 54 | Cancel reason too short | Enter fewer than 10 characters | Form rejected; CDV stays `posted` |
| 55 | Cancel reason stored | After cancelling, view CDV detail | Cancel reason visible on detail page |
| 56 | Audit log after cancel | Check `/audit-log` | Entry: action=`cancel` for this CDV |
| 57 | Cannot cancel a draft CDV | "Cancel" button absent on draft CDV | Cancellation blocked |
| 58 | Cannot cancel a voided CDV | "Cancel" button absent on voided CDV | Cancellation blocked |
| 59 | Staff cannot cancel | Log in as staff, view a posted CDV | "Cancel" button absent or attempt blocked |

### 1.10 Export

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 60 | Export to Excel | Click "Export Excel" on list page | `.xlsx` file downloads; opens in Excel/LibreOffice; rows match list |
| 61 | Export to CSV | Click "Export CSV" on list page | `.csv` file downloads; rows match list |
| 62 | Export respects active filters | Apply status=posted filter, then export | Exported file contains only posted CDVs |

### 1.11 Print

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 63 | Print view loads | GET `/cash-disbursements/<id>/print` (on a posted CDV, `cd_print_access`=`posted_only`) | Print-formatted page renders; shows CDV number, vendor, totals, line items |
| 64 | Print draft blocked | Access print URL on draft CDV when `cd_print_access`=`posted_only` | Blocked or redirect |

---

## PHASE 2 — Hacker Mindset

### 2.1 Authentication & Authorization

| # | Test Case | Action | Expected |
|---|-----------|--------|----------|
| 65 | Access list without login | Navigate to `/cash-disbursements` while logged out | Redirected to `/login` |
| 66 | Access create without login | Navigate to `/cash-disbursements/create` while logged out | Redirected to `/login` |
| 67 | Viewer tries to create | Log in as viewer; GET `/cash-disbursements/create` | Blocked — redirect with permission message |
| 68 | Staff tries to post | Log in as staff; POST `/cash-disbursements/<draft_id>/post` | Blocked; CDV status unchanged |
| 69 | Staff tries to cancel | Log in as staff; POST `/cash-disbursements/<posted_id>/cancel` | Blocked; CDV status unchanged |
| 70 | Access CDV from another branch | Log in, select Branch A; try to GET `/cash-disbursements/<id_from_branch_B>` | 404 Not Found |
| 71 | Edit CDV from another branch | POST to `/cash-disbursements/<other_branch_cdv_id>/edit` | 404 Not Found; CDV unchanged |
| 72 | Post CDV from another branch | POST to `/cash-disbursements/<other_branch_cdv_id>/post` | 404 Not Found; CDV unchanged |

### 2.2 Input Validation

| # | Test Case | Payload | Expected |
|---|-----------|---------|----------|
| 73 | XSS in notes field | `<script>alert('XSS')</script>` | Stored as plain text; script not executed on detail page |
| 74 | XSS in void reason | `<img src=x onerror=alert(1)>` | Stored as plain text; no script execution |
| 75 | Negative amount in expense line | Enter `-1000` as amount | Form rejected or stored as 0; note actual behavior |
| 76 | Non-numeric amount | Enter `abc` as amount | Form rejected |
| 77 | Void reason below minimum | 9 characters exactly | Blocked with error |
| 78 | Cancel reason below minimum | 9 characters exactly | Blocked with error |
| 79 | No JS confirm() popups | Trigger void and cancel modals | Custom HTML modal appears; no `window.confirm()` |
| 80 | CSRF token present | Inspect create/edit/post/void/cancel forms | Hidden `csrf_token` input present in every form |
| 81 | Submit without CSRF token | Manually remove token and submit | 400 Bad Request or CSRF error |

---

## PHASE 3 — Audit Log Verification

Visit `/audit-log` and filter by module = `cash_disbursement` after completing each action.

| # | Action Performed | Expected Audit Entry |
|---|-----------------|----------------------|
| 82 | Create CDV | module=`cash_disbursement`, action=`create`, record_id=CDV id |
| 83 | Edit CDV | module=`cash_disbursement`, action=`update`, record_id=CDV id |
| 84 | Post CDV | module=`cash_disbursement`, action=`post`, record_id=CDV id |
| 85 | Void CDV | module=`cash_disbursement`, action=`void`, record_id=CDV id |
| 86 | Cancel CDV | module=`cash_disbursement`, action=`cancel`, record_id=CDV id |
| 87 | Audit detail shows actor | Click on any CDV audit entry | Username of the actor visible |

---

## PHASE 4 — UX & Responsive Check

Run through each page at three viewport widths: **1280px (desktop)**, **768px (tablet)**, **375px (mobile)**.

| # | Page | Check |
|---|------|-------|
| 88 | CDV List | Table scrolls horizontally on mobile; no clipping |
| 89 | CDV Create Form | Vendor picker, line-item rows usable; no overflow |
| 90 | CDV Detail | JE preview table scrolls; status badge visible |
| 91 | CDV Edit Form | Same as create form |
| 92 | Sidebar (all pages) | Collapses to hamburger at ≤768px; opens/closes correctly |
| 93 | No hardcoded colours | Inspect any modal (void, cancel) — no raw hex values in inline styles |

---

## Bug Log

| # | Date | Page / Route | Description | Severity | Status |
|---|------|--------------|-------------|----------|--------|
| B01 | 2026-06-16 | `/cash-disbursements/create` (POST) | **T75 — No server-side validation for negative expense amounts.** Submitting `amount: -1000` via JSON expense_lines creates a CDV with `total_amount = -1000.00`. No rejection, no error. | Medium | Open |
| B02 | 2026-06-16 | `/cash-disbursements/<id>` (detail) | **T90 — Expense-lines table and JE preview table clip on mobile (375px).** Both tables have `overflow: visible` on their wrapper; content beyond the card edge is hidden instead of scrolling. CDV list page wraps tables correctly (overflow-x: auto) but detail page does not. | Low | Open |
| B03 | 2026-06-16 | Void modal / Cancel modal (detail page) | **T93 — Hardcoded hex colours in modal inline styles.** H3, P, and both buttons in void/cancel modals use raw hex (`#1e293b`, `#475569`, `#e2e8f0`, `#3b82f6`) in `style=""` attributes instead of CSS design-token variables. Violates CLAUDE.md styling convention. | Low | Open |
| B04 | 2026-06-16 | `/dashboard` (after viewer permission redirect) | **Minor — Flash "You do not have permission" appears 3× on dashboard** after viewer attempts to access `/cash-disbursements/create`. Likely a duplicate `flash()` call or session flush issue. | Low | Open |

---

## Test Run Notes

### Skipped Tests (T70–T72)
Branch-isolation tests (T70: GET other-branch CDV → 404; T71: POST edit; T72: POST post) were skipped — only one branch (`Main Branch`) exists in this test environment. Branch isolation is enforced at the `_get_cdv_or_404()` helper (filters by `session['selected_branch_id']`) and confirmed by code review.

### Notable Findings (Non-Bug)
- **Account picker not filtered to expense accounts (create form):** The expense-line account picker shows ALL account types (assets, liabilities, revenue, expenses). Potentially confusing but may be intentional for payment flexibility (e.g., paying a liability directly). Not logged as a bug pending business decision.
- **AP bill Particulars (Notes) not visually marked required:** Creating an AP bill silently resets the Choices.js vendor picker when Notes is empty. This is a pre-existing AP bill issue; not in CDV scope.
- **Print page shows CDV even when Cancelled:** Navigating directly to `/cash-disbursements/1/print` on a Cancelled CDV renders the print page with a "CANCELLED" watermark — intentional and correct.

---

## Test Run Summary

| Metric | Value |
|--------|-------|
| Total test cases | 93 |
| Passed | 87 |
| Failed | 3 (T75, T90, T93) |
| Skipped | 3 (T70, T71, T72 — single-branch environment) |
| Bugs found | 4 (3 test failures + 1 minor flash duplicate) |
| Run date | 2026-06-16 |
| Tester | Claude Code (Playwright automated walk-through) |
| Overall result | CONDITIONAL PASS — core workflows fully functional; 3 low/medium bugs logged |
