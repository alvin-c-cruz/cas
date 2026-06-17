# APV + CDV Historical Seed (2021–present) — Design Spec

**Date:** 2026-06-18
**Status:** Design — approved, pending spec review
**Purpose:** Reports & dashboards demo — populate multi-year APV/CDV history so dashboards, AP aging, monthly trends, and BIR-style reports look realistic.

## Goal

A deterministic generator that loads ~5.5 years (Jan 2021 → 18 Jun 2026) of believable, internally-consistent Accounts Payable Vouchers (APV) and Cash Disbursement Vouchers (CDV) into a freshly reset database, with balanced journal entries and a realistic payment/aging history.

Target volume (heavy density): **~990 APV** (≈15/mo) and **~660 CDV** (≈10/mo) across 66 months.

## A. Mechanism & target

New Flask CLI command **`flask seed-history`** (registered in `app/__init__.py` alongside `seed-db`/`seed-minimal`), implemented under `app/seeds/` (e.g. `app/seeds/history_seed.py`).

Steps:
1. **Full reset** via the existing base path: drop → recreate tables → load base fixtures (admin user, Main branch, full 173-account COA, VAT categories, WHT codes, settings). Reuse whatever `seed-db` already does for the base — do not re-implement the COA.
2. **Ensure reference data** (Section B): create the seeded `accountant` user and the ~12 demo vendors if absent; resolve expense-account leaves and VAT/WHT codes from the seeded set.
3. **Generate** the 2021→present APV + CDV history programmatically (Sections C–E).
4. Print a summary (counts per year, total posted/paid/partial/outstanding, JE balance check result).

Properties:
- **Deterministic:** a fixed RNG seed (e.g. `random.Random(20210101)`) drives all jitter (counts, amounts, vendor/account/lag choices) so re-runs reproduce the same dataset.
- **Idempotent via reset:** the command always starts from a clean DB, so there is no append/collision logic to maintain.
- **Reuses real posting logic** — never hand-rolls JE lines:
  - APV: build `AccountsPayable` + line items → `ap.calculate_totals()` → apply WHT via the same path `create()` uses (`_apply_overrides`) → `db.session.flush()` → `_post_ap_je(ap, user_id)` → set `status='posted'`, `posted_by_id`, `posted_at`, and the JE `status='posted'`.
  - CDV: build `CashDisbursementVoucher` + `CDVApLine`/`CDVExpenseLine` → `cdv.calculate_totals()` → `flush` → `_post_cdv_je(cdv, user_id)` → set posted fields → `_apply_ap_payments(cdv)` to update each paid APV's `amount_paid`/`balance`/`status`.
  - Document numbers via `generate_ap_number()` / `generate_cdv_number()` (PREFIX-YYYY-MM-NNNN), generated in chronological insert order so numbering matches dates.
- **Bypasses only the view-layer closed-period date guard** (`validate_transaction_date_with_flash`) — the seed inserts through model helpers, not the create views, so historical dates post freely.

## B. Reference data

**Users:** keep base `admin`; add one `accountant` user (role `accountant`, active, known password). APVs/CDVs are created by the accountant and posted by accountant or admin so signatories + audit trail look real.

**Vendors (~12).** Created if absent, each with a default VAT category and WHT code drawn from the seeded set (exact codes bound in the plan after inspecting `seed-db` output). "Recurring" vendors get one bill every month for smooth trend lines.

| Vendor | Category | Recurring? | Typical APV total band | VAT | WHT |
|---|---|---|---|---|---|
| Sunrise Realty Mgmt | Office rent | monthly | ₱40k–50k | 12% svc | 5% (rental) |
| MetroPower Electric | Utilities (power) | monthly | ₱8k–13k | exempt/0% | none |
| ClearWater Utilities | Utilities (water) | monthly | ₱1.5k–4k | exempt/0% | none |
| GlobeLink Telecom | Telecom/internet | monthly | ₱3k–6k | 12% svc | none |
| Mega Office Supplies | Office supplies | frequent | ₱5k–20k | 12% goods | 1% (WC158) |
| Capitol Stationers | Office supplies | frequent | ₱3k–12k | 12% goods | 1% (WC158) |
| TechServe IT Solutions | IT services | occasional | ₱15k–55k | 12% svc | 2% (WC100) |
| Bautista Law Office | Legal/professional | occasional | ₱20k–60k | 12% svc | 10% (WC010) |
| QuickCourier Express | Courier/delivery | frequent | ₱1.5k–5k | 12% svc | 2% |
| FleetFuel Station | Fuel | frequent | ₱4k–15k | 12% goods | 1% |
| FixIt Maintenance | Repairs/maintenance | occasional | ₱5k–30k | 12% svc | 2% (WC100) |
| BrightAd Marketing | Marketing | occasional | ₱10k–45k | 12% svc | 2% |

**Expense accounts:** each category maps to a real expense leaf in the seeded COA (Rent, Light & Water/Utilities, Office Supplies, Professional Fees, Repairs & Maintenance, Fuel & Oil, Advertising, Communication, etc.). The plan resolves exact codes from the seeded COA; if a needed leaf is missing it falls back to a present expense leaf and logs the substitution.

## C. Generation model (per month, Jan 2021 → Jun 2026)

- **APV count:** ~15/mo, jitter 13–17. **CDV count:** ~10/mo, jitter 8–12. June 2026 truncated at the 18th (≈ pro-rata count).
- **APV:** mostly 1 line item; ~20% have 2–3 lines. Line amount drawn from the vendor's band; `line_total` is VAT-inclusive (VAT extracted per the line's category, per CAS mechanics). WHT per vendor default. Recurring vendors (rent, power, water, telecom) emit exactly one bill/month dated near a fixed day; the rest are scattered through the month.
- **CDV:** ~70% pay APVs (Section A), ~30% direct expenses (Section B, drawn from the same vendor/account/amount logic). Payment method mix ~60% check / 40% cash; check CDVs get a check number/date/bank.
- `vendor_invoice_number`: a synthetic `INV-YYYY-####` per APV (so VAT/WHT posting validations that require an invoice are satisfied).

## D. Aging & payment model

- **2021 → ~mid-2025 APVs:** fully paid by a CDV dated **15–45 days after** the bill date → APV `status='paid'`, `balance=0`.
- **Last ~12 months (Jul 2025 → Jun 2026):** deliberate spread so AP-aging buckets are all populated as of 2026-06-18:
  - most `paid`,
  - some `partially_paid` (a CDV applies part of the balance),
  - some `posted`/outstanding (no CDV yet) landing in current / 31–60 / 61–90 / 90+ buckets.
- **Recent non-posted tail (2026 only):** a handful of `draft` APVs/CDVs and a couple of `voided` ones for status variety. Historical years (2021–2025) remain clean (all posted/paid). No `cancelled` needed unless trivially added.
- Payment lag and partial/outstanding selection are RNG-driven but seeded, so the aging snapshot is reproducible.

## E. Posting & integrity

- Posted APV JE: debit expense (net) + debit Input VAT (per VAT buckets) + credit AP-Trade + credit WHT-payable (when WHT applies) — assembled by `_post_ap_je`.
- Posted CDV JE: debit AP-Trade (for Section A) and/or debit expense+Input VAT (Section B) + credit WHT-payable + credit Cash/Bank — assembled by `_post_cdv_je`.
- Paying via CDV runs `_apply_ap_payments`, transitioning the APV to `partially_paid`/`paid` exactly as the real post path does.
- **Accounting periods:** NOT created or enforced (direct model insert). Out of scope by decision.
- Cash/Bank account for CDVs: a seeded Cash in Bank / Cash on Hand leaf, chosen per payment method.

## F. Out of scope

- Receipts / Accounts Receivable, Sales Invoices, attachments.
- Multi-branch (everything posts to Main).
- Accounting-period open/close records and period reports.
- Appending to a non-empty DB (the command always resets).
- Realistic vendor master beyond the ~12 demo vendors and the figures above.

## G. Verification

A pytest test (`tests/integration/test_history_seed.py`) runs the generator's core against a **temp/in-memory DB on a short slice** (e.g. 3 months) and asserts:
1. APV and CDV counts land in the expected per-month bands.
2. **Every journal entry balances** (Σ debit == Σ credit) for all seeded posted docs.
3. Payment transitions are correct: a fully-applied CDV sets the APV to `paid` with `balance==0`; a partial sets `partially_paid` with `0 < balance < total`.
4. AP aging has at least one outstanding APV in the recent window.

The full `flask seed-history` run is then executed once manually; the command's summary output (counts + JE-balance check) is the acceptance evidence. Per project rule, any bug found is reported and fix-approved before fixing.

## Open implementation notes (resolved in the plan)

- Bind exact VAT category codes, WHT codes, expense-leaf codes, and Cash/Bank codes from the actual `seed-db` COA/VAT/WHT output.
- Confirm `_post_ap_je` signature and that `calculate_totals()` exists on `AccountsPayable` (CDV has `calculate_totals`; verify the APV equivalent and the WHT-application path used by `create()`).
- Confirm `generate_ap_number`/`generate_cdv_number` derive the running sequence from existing rows (so chronological insertion yields correct monthly sequences).
