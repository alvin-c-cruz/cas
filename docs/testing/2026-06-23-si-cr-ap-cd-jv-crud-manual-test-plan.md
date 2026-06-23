# Manual CRUD + Lifecycle Test Plan — SI / CR / AP / CD / JV

_Date: 2026-06-23 · Type: manual UI runbook (browser) · Scope: full transaction lifecycle_

Covers the five transaction documents end-to-end through the running app's UI:
**SI** Sales Invoices · **CR** Cash Receipts (CRV) · **AP** Accounts Payable (APV) ·
**CD** Cash Disbursements (CDV) · **JV** Journal Voucher.

For each you test: **Create (draft) → Read (view+list) → Update (edit draft) → Post →
Cancel / Void → Delete**, plus the cross-cutting checks every document needs:
document numbering, VAT/WHT math, branch scoping, closed-period block, role gating, and
the audit trail. Record **Pass / Fail / N/A** and a note per case.

> Test by **observable outcome**, not internal mechanism. Where a step says "the books are
> reversed," verify it in the General Ledger / Trial Balance / the document's JE preview —
> don't assume how it was done.

---

## 1. Prerequisites & setup

1. **Run the app**: `python flask_app.py` (port 5000). Use a DB you can dirty — confirm `.env`
   `SQLALCHEMY_DATABASE_URI` first (currently `cas_demo.db`); do NOT run destructive cases against
   real `ric.db`.
2. **Seed data present**: COA (incl. AR `10201`, Creditable WHT `10212`, AP `20101`, WHT-Payable
   `20301`, Output/Input VAT accounts, cash/bank accounts, revenue + expense accounts), at least one
   active **Customer**, one active **Vendor**, VAT categories, and WHT codes. Run `flask seed-db` if missing.
3. **Login**: admin `admin` / `admin123`.
4. **Branch**: after login, pick a branch (e.g. `MAIN`) when prompted; the branch selector is in the
   sidebar. All five modules require a selected branch.
5. **Non-admin users for role gating (§Cross-cutting C5)**: no staff/accountant/viewer users are
   seeded — before the role tests, create three via **Admin → Users**: one `accountant`, one `staff`,
   one `viewer` (note their passwords). Per project rule, do day-to-day accounting as the
   **accountant**, not admin.
6. **A second branch** (for branch-scoping §C3): create one via **Admin → Branches** if only `MAIN` exists.

### How to verify results
- **Audit trail**: open **Audit Log** (sidebar) and confirm an entry exists for each create/update/
  post/cancel/void/delete — correct action, document reference, and actor. (Required for every write.)
- **The books**: open the document's **detail page JE preview**, and cross-check the **General Ledger**
  / **Trial Balance** for the affected accounts. A correct cancel/void leaves the net effect at zero.
- **Lists/filters**: use the module **list page** (search, status filter, date filter) and the
  **Excel/CSV/Print** exports.

---

## 2. Per-module parameters

The shared lifecycle sequence in §3 is run once per module using these parameters.

| | **SI** | **CR (CRV)** | **AP (APV)** | **CD (CDV)** | **JV** |
|---|---|---|---|---|---|
| Sidebar nav | Sales Invoices (Bill Client) | Cash Receipts (Collection) | Accounts Payable (Enter Bill) | Cash Disbursements (Pay Bill) | Journal Voucher |
| List URL | `/sales-invoices` | `/cash-receipts` | `/accounts-payable` | `/cash-disbursements` | `/journal-entries` (may redirect to the journals book) |
| Launch button | + Enter Invoice | + Enter CRV | + Enter APV | + Enter CDV | + Enter Journal Voucher |
| In-form submit | Save / Update | Save / Update | Save / Update | Save / Update | Save |
| Counterparty | Customer | Customer | Vendor | Vendor | — (manual accounts) |
| Doc number | `invoice_number` — **user-typed pre-printed** serial | `crv_number` — **user-typed pre-printed** serial | `ap_number` — **system** `AP-YYYY-MM-NNNN` | `cdv_number` — **system** `CD-YYYY-MM-NNNN` | `entry_number` — system `JV-YYYY-MM-####` |
| Cash/bank leg | — (AR-based) | **Dr** cash/bank | — (AP-based) | **Cr** cash/bank | manual |
| Posted JE (core legs) | Dr AR + Dr Creditable WHT; Cr Output VAT; Cr Revenue | Dr Cash; Cr AR / Cr Revenue + Cr Output VAT; (WHT) | Dr Expense + Dr Input VAT; Cr AP; Cr WHT-Payable | Cr Cash; Dr AP / Dr Expense + Dr Input VAT; Cr WHT-Payable | as entered (must balance) |
| Line VAT / WHT | Output VAT + WHT, per line, with overrides | Output VAT + WHT, per line, with overrides | Input VAT + WHT, per line, with overrides | Input VAT + WHT, per line, with overrides | none |
| Create role | staff+ | staff+ | staff+ | staff+ | **accountant+** |
| Cancel/Void role | accountant/admin | accountant/admin | accountant/admin | accountant/admin | accountant/admin |

Notes: SI/CR document numbers are **typed by the user** (pre-printed BIR forms) — the form pre-fills a
suggestion but the typed value is saved and must be unique. AP/CD/JV numbers are **system-generated** and
should not be editable. JV is created through the journals book and differs from the other four (see §5).

---

## 3. Shared lifecycle sequence (run for SI, CR, AP, CD)

Run this whole sequence once per module. Use today's date unless a case says otherwise. Record P/F/NA + note.

| ID | Step | Expected result |
|----|------|-----------------|
| **L1 Create-draft** | From the list page, click the launch button. Fill the header (counterparty, date, reference) and **one line item** (account, amount, a VAT category, no WHT). Click **Save**. | Saved as **draft**; redirected to its detail page; document number shown; totals computed (VAT extracted from the VAT-inclusive amount). No JE posted to the books yet (or a *draft* JE only). |
| **L2 Read-detail** | View the detail page. | Header, line items, computed VAT/WHT, totals, and a **JE preview** all render; status = **draft**. |
| **L3 Read-list** | Return to the list. | The new draft appears with its number, counterparty, date, amount, and a **draft** badge. Search by number and by counterparty both find it. |
| **L4 Update-draft** | Edit the draft: change the amount / add a second line, **Update**. | Changes persist; totals recomputed; still **draft**. |
| **L5 Post** | On the detail page, click **Post**. | Status → **posted**. The posted **JE is balanced** (total debits = total credits) and hits the expected accounts (see §2 row "Posted JE"). Confirm in the JE preview and in the **General Ledger** for each account. |
| **L6 Edit-after-post blocked** | Try to edit the posted document (visit its `/edit` URL directly). | Rejected — only **draft** documents are editable (flash + redirect). |
| **L7 Cancel (posted)** | On a posted document, click **Cancel**, supply a reason. | Status → **cancelled**; a **reversing entry** appears in the books so the net effect of this document is **zero** (verify the affected accounts in the GL/Trial Balance return to pre-post values). The document number is **not** reused. |
| **L8 Void** | Create + post a *second* document, then click **Void** (supply reason). | Document marked **voided**; verify the books no longer carry its effect (no live JE contribution). Confirm the exact void behavior for this module and note it (void may apply to drafts and/or remove the JE — record what you observe). |
| **L9 Delete-draft** | Create a fresh draft, then delete it (if a delete/void control exists for drafts). | Draft removed from the list; no orphan JE remains in the books. |
| **L10 Audit** | Open the **Audit Log**. | One entry each for L1 create, L4 update, L5 post, L7 cancel, L8 void, L9 delete — each with the correct action, the document number as reference, and **admin** (or the acting user) as actor. |

---

## 4. Per-module specific cases

### 4.1 SI — Sales Invoices
- **SI-1 Pre-printed number is honored**: on create, change the pre-filled `invoice_number` to a distinct serial (e.g. `OR-SI-7001`) and Save → the **typed** value is saved (not overwritten).
- **SI-2 Duplicate number rejected**: create a second SI with the same `invoice_number` → friendly "already exists" error, no second record.
- **SI-3 Posted JE shape**: post an SI with VAT + a WHT line → JE is **Dr AR (gross)** + **Dr Creditable WHT (10212)**; **Cr Output VAT** (per category bucket); **Cr Revenue (net)**; balanced.
- **SI-4 Multi-category VAT**: two lines with two different VAT categories → two distinct Output-VAT credit lines.

### 4.2 CR — Cash Receipts (CRV)
- **CR-1 Pre-printed number is honored** (fixed 2026-06-23): change the pre-filled `crv_number` to a distinct serial → the **typed** value is saved; **CR-2 duplicate rejected** with a friendly message.
- **CR-3 Cash leg**: post a CRV → JE **Dr** the selected **cash/bank** account for the total; AR-applied lines **Cr AR**; direct-revenue lines **Cr Revenue + Cr Output VAT**.
- **CR-4 Open-invoice application**: applying a receipt to an open SI reduces that invoice's balance; over-application is blocked.

### 4.3 AP — Accounts Payable (APV)
- **AP-1 System number**: `ap_number` is `AP-YYYY-MM-NNNN`, **not editable**, and increments within the month.
- **AP-2 Posted JE shape**: **Dr Expense (net) + Dr Input VAT** (per category bucket); **Cr AP (20101)**; **Cr WHT-Payable (20301)** when WHT applied; balanced.
- **AP-3 Unmapped VAT category blocks save**: a VAT-bearing line whose category has no Input-VAT account → save blocked with a clear message.

### 4.4 CD — Cash Disbursements (CDV)
- **CD-1 System number**: `cdv_number` is `CD-YYYY-MM-NNNN`, not editable, monthly increment.
- **CD-2 Posted JE shape**: **Cr Cash** for the total; AP-applied lines **Dr AP (20101)**; expense lines **Dr Expense + Dr Input VAT**; **Cr WHT-Payable** when withheld; balanced.
- **CD-3 Pay an open bill**: applying a CDV to an open AP reduces that bill's balance; over-application blocked.
- **CD-4 CRV↔CDV parity**: spot-check that money math (VAT buckets, over-application guard, reversing-entry on cancel) behaves the same way as CR (they are mirror modules).

### 4.5 JV — Journal Voucher (different shape — §5)

---

## 5. JV — Journal Voucher (manual entry)

JV has no counterparty, no VAT/WHT, and **accountant/admin only**. It is created through the journals
book ("Journal Voucher" in the sidebar). Run:

| ID | Step | Expected result |
|----|------|-----------------|
| JV-1 Create-draft | Enter date + description, add **≥2 lines** (account + a debit OR a credit each) that **balance**. Save. | Draft created; `entry_number` system-assigned (`JV-YYYY-MM-####`). |
| JV-2 Unbalanced blocked | Try to save/post with debits ≠ credits. | Rejected — must balance. |
| JV-3 One-sided line blocked | A line with both debit and credit, or zero on both. | Rejected. |
| JV-4 Post | Post the balanced draft. | Status → **posted**; lines hit the GL exactly as entered; balanced. |
| JV-5 Cancel/reverse | Cancel a posted JV (with reversal date). | Status → **cancelled**; a reversing entry nets it to zero. |
| JV-6 Delete-draft | Delete a draft JV. | Removed; no GL effect. |
| JV-7 Role | As **staff**, attempt to reach JV create. | Denied (JV is accountant/admin only — stricter than the other four). |
| JV-8 Audit | Audit Log shows create/post/cancel/delete entries. | Correct action + reference + actor. |
| JV-9 Numbering display | Confirm the UI shows the `JV-` (or source-doc) number, never a raw internal `JE-####`. | Per project rule, `entry_number` `JE-` is internal-only. |

---

## 6. Cross-cutting test groups (apply to each module per the matrix)

| ID | Test | SI | CR | AP | CD | JV |
|----|------|----|----|----|----|----|
| **C1 Numbering** | New doc gets the right number; SI/CR honor a user-typed pre-printed serial & reject duplicates; AP/CD/JV are system-generated & non-editable; sequence is correct. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C2 VAT/WHT math** | VAT is **extracted** from the VAT-inclusive line amount (not added on top); WHT computed on the net-of-VAT base; `vat_override`/`wt_override` apply and the JE still balances. | ✓ | ✓ | ✓ | ✓ | n/a |
| **C3 Branch scoping** | A document created under branch A does **not** appear in the list when branch B is selected; pickers (cash/bank, etc.) show only the selected branch's options where applicable. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C4 Closed-period block** | Close the period for the document's date (Periods/Year-End), then try to **create** and to **post** into it → blocked with a flash; no JE written. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C5 Role gating** | **staff**: can create/edit drafts & post the four transaction docs, but **cannot** cancel/void (accountant/admin only) and **cannot** reach JV create. **viewer**: read-only (no create/edit/post/cancel). **accountant**: full transaction access. Verify each by logging in as that user and confirming the buttons are hidden AND the direct POST/URL is rejected server-side. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C6 Audit** | Every create/update/post/cancel/void/delete writes an Audit Log entry with correct action, document reference, and actor. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C7 Validation/negatives** | Required fields enforced (counterparty, date, ≥1 line); negative/zero amounts rejected where invalid; submitting with no lines blocked; editing/posting a non-existent id → 404. | ✓ | ✓ | ✓ | ✓ | ✓ |
| **C8 Exports/print** | List Excel/CSV exports and the document print view render and reflect the current filter (no stale/leaked rows). | ✓ | ✓ | ✓ | ✓ | n/a |

> **C5 note (server-side enforcement):** hiding a button is not access control. For at least one
> denied action per role, also hit the action's URL directly (e.g. POST `/sales-invoices/<id>/cancel`
> as staff) and confirm a server-side rejection (flash + redirect), not just a missing button.

---

## 7. Items to confirm during the run (don't assume)

- **Void vs Cancel semantics** per module: confirm from which status each is allowed and the exact book
  effect (reversing entry vs draft/JE removal). The matrix in §2 states the *intended* legs; record the
  observed behavior in L7/L8 and flag any divergence (esp. SI↔CR and CD↔CR parity).
- **JV entry point**: the `/journal-entries` list may redirect to the redesigned journals book — drive
  the JV tests from the actual "Journal Voucher" sidebar destination.
- **CR/SI pre-printed number field**: confirm the field is user-editable (not locked) and that a typed
  value persists (CR was fixed for this on 2026-06-23).

---

## 8. Sign-off

| Module | CRUD (L1–L4,L9) | Post (L5–L6) | Cancel/Void (L7–L8) | Cross-cutting (C1–C8) | Tester | Date | Result |
|--------|---|---|---|---|---|---|---|
| SI |  |  |  |  |  |  |  |
| CR |  |  |  |  |  |  |  |
| AP |  |  |  |  |  |  |  |
| CD |  |  |  |  |  |  |  |
| JV |  | — |  | C1,C3–C7 |  |  |  |

Log every bug found with: module, test ID, steps, expected vs actual, severity. Per project rule,
**report bugs and get a fix approved before fixing** — keep testing and logging while waiting.
