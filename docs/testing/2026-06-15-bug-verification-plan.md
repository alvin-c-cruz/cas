# CAS Bug Verification Plan

**System:** http://127.0.0.1:5000/  
**Date:** 2026-06-15  
**Tester:** Admin  
**Source:** Bug tracker `project-bug-tracker.md` — full system test 2026-06-14  
**Scope:** Verify all 17 open bugs; confirm BUG-10 regression after COA fix

---

## Pre-Test Setup

| # | Step |
|---|------|
| S1 | Log in as `admin` / `admin123` |
| S2 | Ensure server is running at `http://127.0.0.1:5000/` |
| S3 | Open browser DevTools (F12) — Network and Console tabs will be needed |
| S4 | Reset DB if needed: `/reset-database` (clean state avoids false positives) |

---

## Status Legend

| Status | Meaning |
|--------|---------|
| **OPEN** | Bug still present — record repro details |
| **FIXED** | Bug no longer reproducible |
| **REGRESSED** | Bug was fixed but reappeared |
| **INFO** | Behavior changed but differently than expected |

---

## 🔴 High — Core Functionality

### BUG-10: COA missing AR, Revenue, Cash in Bank accounts *(REGRESSION CHECK — was fixed)*

**Fix applied:** `seed_minimal()` expanded from 22 → 28 accounts. Run against a freshly seeded DB.

| # | Step | Expected |
|---|------|----------|
| 1 | Run `/reset-database` to get fresh seed | COA seeded with 28 accounts |
| 2 | Navigate to `/accounts` (Chart of Accounts) | See accounts including 10102, 10201, 10212, 20401, 30100, 40000 |
| 3 | Verify `10201 Accounts Receivable - Trade` exists | Visible as a leaf account under Assets |
| 4 | Verify `10102 Cash in Bank` exists | Visible |
| 5 | Verify `20401 Output VAT Payable` exists | Visible |
| 6 | Verify `40000 Sales Revenue` exists | Visible |
| 7 | Navigate to Sales Invoice → new SI | No "AR Account (10201) not found" warning |
| 8 | Add a line item with a VAT-bearing category (V12DG) | VT dropdown populated; no ValueError on post |
| **Result** | | **FIXED / REGRESSED** |

---

### BUG-02: VAT/WHT dropdowns empty in Sales Invoice line items

**Context:** VT shows only "No VAT", WT shows only "None" — even with 7 VAT categories and 3 WHT codes configured.

| # | Step | Expected |
|---|------|----------|
| 9 | Log in as admin, navigate to Sales Invoice → create new SI | SI create form loads |
| 10 | Add a line item row | Line item row appears |
| 11 | Inspect the VT (VAT Type) dropdown | Should show: VEX, V0, INV, V12CG, V12DG, V12SV, V12IM |
| 12 | If dropdown is empty, open DevTools → Network tab, refresh SI create page | Look for any `/api/vat-categories` or similar fetch request |
| 13 | Check Console tab for JS errors | Note any fetch failures or 404s |
| 14 | Inspect the WT (Withholding Tax) dropdown | Should show at least 3 codes |
| 15 | If still empty, navigate to `/vat-categories` and confirm categories exist | 7 categories should be listed |
| **Result** | | **OPEN / FIXED** |
| **Notes** | Record exact dropdown contents and any console errors | |

---

### BUG-SEC-01: No rate limiting / account lockout on login

**Context:** 10+ rapid failed login attempts all return HTTP 200; no lockout or CAPTCHA.

| # | Step | Expected (current behavior) | Should be |
|---|------|-----------------------------|-----------|
| 16 | Open DevTools → Network tab | | |
| 17 | Submit 5 failed login attempts with wrong password for `admin` | All return HTTP 200 | HTTP 429 or lockout after N failures |
| 18 | Note response status and any `Retry-After` header | HTTP 200 each time | HTTP 429 with Retry-After |
| 19 | Check if account is locked after 10 attempts | No lockout | Should lock or throttle |
| **Result** | | **OPEN (KNOWN BUG — no fix yet)** |

---

## 🟠 Security — Medium-High

### BUG-SEC-02: HTTP 200 returned on failed login

| # | Step | Expected (current) | Should be |
|---|------|--------------------|-----------|
| 20 | Open DevTools → Network tab | | |
| 21 | Submit wrong credentials at `/login` | HTTP 200 | HTTP 401 |
| 22 | Note exact response status code | 200 | 401 |
| **Result** | | **OPEN (KNOWN BUG — no fix yet)** |

---

### BUG-SEC-03: CSRF cookie not HttpOnly

| # | Step | Expected (current) | Should be |
|---|------|--------------------|-----------|
| 23 | Log in as any user | | |
| 24 | Open DevTools → Console tab | | |
| 25 | Type `document.cookie` and press Enter | CSRF token visible in output | Cookie should NOT appear (HttpOnly) |
| 26 | Open DevTools → Application → Cookies → `127.0.0.1` | Find `csrftoken` or `session` cookie; check HttpOnly column | HttpOnly = ✓ |
| **Result** | | **OPEN (KNOWN BUG — no fix yet)** |

---

## 🟡 Medium — UX / Presentation

### BUG-01: AP Voucher page title shows "Save Draft"

| # | Step | Expected |
|---|------|----------|
| 27 | Navigate to AP Vouchers → create new APV | Page loads |
| 28 | Check the browser tab title (`<title>` in page source) | Should be "New AP Voucher" or similar |
| 29 | Check the `<h1>` page heading | Should match intent, not "Save Draft" |
| **Result** | | **OPEN / FIXED** |

---

### BUG-05: "-0.00" displayed on WHT fields

**Context:** "Less: WHT" shows -0.00 when no WHT is applied. Affects SI and APV.

| # | Step | Expected |
|---|------|----------|
| 30 | Create or view a Sales Invoice with no WHT applied | "Less: WHT" row |
| 31 | Check the displayed WHT value | Should show `0.00` or be hidden; **not** `-0.00` |
| 32 | Repeat on AP Voucher with no WHT | Same check |
| **Result** | | **OPEN / FIXED** |

---

### BUG-07: Audit Log last column truncated

| # | Step | Expected |
|---|------|----------|
| 33 | Navigate to Audit Log (`/audit` or similar) | Audit log table loads |
| 34 | Check the rightmost column — action type labels like `BRANCH_SWITCH`, `LOGIN_SUCCESS` | Should be fully visible |
| 35 | Check if horizontal scroll is available | Table should handle long labels without clipping |
| **Result** | | **OPEN / FIXED** |

---

### BUG-08: AP Voucher vendor dropdown 2-second delay, no loading indicator

| # | Step | Expected |
|---|------|----------|
| 36 | Create new AP Voucher | APV create form loads |
| 37 | Select a vendor from the vendor picker | After selection, line items should unlock |
| 38 | Time how long line items stay locked/disabled after vendor selection | Should be instant or show a loading spinner |
| 39 | Note whether any spinner, skeleton, or "loading..." indicator appears | Should have visual feedback during the delay |
| **Result** | | **OPEN / FIXED** |

---

### BUG-09: Double "for" in Journal empty-state messages

**Context:** "No [X] entries found for for the month of june 2026" — also lowercase month.

| # | Step | Expected |
|---|------|----------|
| 40 | Navigate to AP Journal for a month with no entries | Empty-state message shown |
| 41 | Read the full message | Should say "...found for the month of June 2026" (one "for", capitalized month) |
| 42 | Repeat for CD Journal (Cash Disbursements Journal) | Same check |
| **Result** | | **OPEN / FIXED** |

---

### BUG-13: AP Voucher Description field not visible in line items

| # | Step | Expected |
|---|------|----------|
| 43 | Create new AP Voucher, add at least one line item | Line item row appears |
| 44 | Count the visible columns in the first line item row | Should include: Description, Amount, VT, WT, Account Title |
| 45 | Check specifically whether a **Description** input is visible | Should be present; **not** just Amount / VT / WT / Account |
| **Result** | | **OPEN / FIXED** |

---

## 🟢 Low — Polish

### BUG-06: Register page hardcodes company name

| # | Step | Expected |
|---|------|----------|
| 46 | Navigate to `/register` (log out first) | Register page loads |
| 47 | Check what company name appears on the page | Should pull from AppSettings (same as login page) |
| 48 | Navigate to `/login` for comparison | Note whether names match |
| **Result** | | **OPEN / FIXED** |

---

### BUG-11: Stale JS validation errors on Registration

**Context:** "This field is required" error persists even after the field is filled; form still submits correctly.

| # | Step | Expected |
|---|------|----------|
| 49 | Navigate to `/register` | Register form loads |
| 50 | Click Submit without filling any fields | Validation errors appear on all required fields |
| 51 | Now fill in one of the fields that showed an error | Error should clear immediately on fill |
| 52 | Check if the error label persists after filling | Should disappear; bug = it stays |
| **Result** | | **OPEN / FIXED** |

---

### BUG-12: Cash Disbursements list missing Export buttons

| # | Step | Expected |
|---|------|----------|
| 53 | Navigate to Cash Disbursements list | CD list loads |
| 54 | Check for Export Excel / Export CSV buttons | Should have them (Sales Invoice list has them for comparison) |
| 55 | Navigate to Sales Invoice list for comparison | Confirm SI list has Export Excel + Export CSV |
| **Result** | | **OPEN (missing feature — needs implementation)** |

---

### BUG-14: VAT/WHT Description columns all show "-"

**Context:** Descriptions were never entered during setup — this is a data gap, not a code bug.

| # | Step | Expected |
|---|------|----------|
| 56 | Navigate to `/vat-categories` | VAT category list loads |
| 57 | Check the Description column | Likely shows "-" or empty — this is **expected** if descriptions were never entered |
| 58 | Edit one VAT category and add a description | Description saves and displays |
| **Result** | | **INFO (data gap — not a code bug; close if description saves correctly)** |

---

## ⚙️ Config / Setup (expected behavior — document, don't fix)

### BUG-03: No approved emails → registration blocked

| # | Step | Expected |
|---|------|----------|
| 59 | Delete all approved emails at `/approved-emails` | None remaining |
| 60 | Log out, navigate to `/register`, submit with any email | Observe result — does form block or allow registration? |
| 61 | Note exact behavior for onboarding docs | Expected: blocked or user created but inactive with no approved-email match |
| **Result** | | **INFO (expected behavior — document in onboarding guide)** |

---

### BUG-04: "Forgot password?" is a dead link

| # | Step | Expected |
|---|------|----------|
| 62 | Navigate to `/login` | Login page loads |
| 63 | Click "Forgot password?" | Should navigate somewhere |
| 64 | Note response — likely 404 | Expected: 404 (incomplete feature) |
| **Result** | | **INFO (known incomplete feature — low urgency)** |

---

## Summary Sheet

Fill in after testing:

| Bug ID | Description | Result | Notes |
|--------|-------------|--------|-------|
| BUG-10 | COA missing accounts *(regression check)* | | |
| BUG-02 | VAT/WHT dropdowns empty in SI | | |
| BUG-SEC-01 | No rate limiting on login | OPEN (known) | |
| BUG-SEC-02 | HTTP 200 on failed login | OPEN (known) | |
| BUG-SEC-03 | CSRF cookie not HttpOnly | OPEN (known) | |
| BUG-01 | APV page title "Save Draft" | | |
| BUG-05 | "-0.00" on WHT fields | | |
| BUG-07 | Audit Log column truncated | | |
| BUG-08 | APV vendor dropdown delay, no spinner | | |
| BUG-09 | Double "for" in journal empty state | | |
| BUG-13 | APV Description field missing from line items | | |
| BUG-06 | Register page hardcoded company name | | |
| BUG-11 | Stale JS validation errors on register | | |
| BUG-12 | CD list missing Export buttons | | |
| BUG-14 | VAT/WHT Description shows "-" | INFO (data gap) | |
| BUG-03 | No approved emails blocks registration | INFO (expected) | |
| BUG-04 | Forgot password = 404 | INFO (incomplete) | |

---

## Testing Order

Run in this sequence to avoid state interference:

1. **BUG-10** — regression check first; needs fresh DB (reset before starting)
2. **BUG-02** — SI VAT/WHT dropdowns (needs accounts from BUG-10 fix to be present)
3. **BUG-13** — APV line item Description (APV tests together)
4. **BUG-08** — APV vendor dropdown delay (same session)
5. **BUG-01** — APV page title (quick check while on APV)
6. **BUG-05** — "-0.00" on WHT (SI and APV both; run after above)
7. **BUG-09** — Journal empty state (navigate to journals)
8. **BUG-07** — Audit Log column (quick visual check)
9. **BUG-12** — CD list export buttons (quick check)
10. **BUG-06** — Register page company name (log out, check `/register`)
11. **BUG-11** — Stale JS validation on register (same page)
12. **BUG-03** — Approved emails behavior (delete all, test register)
13. **BUG-04** — Forgot password link (quick check)
14. **BUG-14** — VAT/WHT descriptions (data gap confirm)
15. **BUG-SEC-02** — HTTP status on failed login (DevTools)
16. **BUG-SEC-03** — CSRF cookie HttpOnly (DevTools)
17. **BUG-SEC-01** — Rate limiting brute force (last — generates noise in logs)
