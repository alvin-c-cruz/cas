# Food Toll Packing Demo Dataset — Design

**Date:** 2026-07-03
**Status:** Design — pending user review
**Type:** New seed-data generator (presentation demo). No app/model/migration changes.

## Goal

A believable **contract food manufacturer / toll packer** demo — *SavorPack Food Manufacturing Corp.* (rename freely) — with **two full fiscal years (2024, 2025) plus 2026 year-to-date through June**, **single MAIN branch**, so a live walkthrough of every CAS report (TB, Income Statement, Balance Sheet, Cash Flow, GL, AP/AR aging, BIR sales/purchases, Books of Accounts) shows realistic, populated, balanced numbers. Built as a **new, separate seeder** (`flask seed-food-demo`) that leaves the existing Zhiyuan Construction demo untouched.

## Readiness (assessed 2026-07-03)

- **Schema ready:** `cas_demo.db` is at migration head `f826f2cca271`.
- The existing `flask seed-demo` builds *Zhiyuan Construction* with its own construction COA — **not** reusable for this. Hence a new generator.
- Transaction seeders are **not idempotent**; a rebuild is delete-DB → `flask db upgrade` → seed. `.env` already targets `cas_demo.db` (the correct demo DB).

## Business model (decided)

Full **contract manufacturing with inventory** (not pure toll service): the company buys raw materials + packaging, manufactures/packs food products it owns, and sells finished goods (12% output VAT). Because **CAS has no inventory/production module** (the `products` table is master-data only; `track_inventory`/costing were deliberately not built), the manufacturing/inventory story is represented **entirely at the GL level** — inventory as COA balances, production as journal entries. No stock cards / quantity-on-hand appear (the app has none). Inventory method = **full periodic**: Raw Materials → Work-in-Process → Finished Goods → COGS, via journal vouchers.

## Company identity (proposed)

- Name `SavorPack Food Manufacturing Corp.`, VAT-registered, TIN + address (demo values), calendar fiscal year (`fiscal_year_start = 01`), single **MAIN** branch, admin user `admin`/`admin123` (reuse the standard seed identity).
- Accounting periods opened **Jan 2024 → Jun 2026** (every month in the span).

## Chart of Accounts

**Preserve** all 23 existing baseline accounts (the 9 parent groups + their leaves). **`account_type` is the single source of FS placement** — the additions below use the canonical rich types from `app/accounts/account_types.py`; `classification` (Current/Non-Current) is set for every Asset/Liability; `normal_balance` follows `DEFAULT_NORMAL_BALANCE` (Accumulated Depreciation is an Asset with a **credit** normal balance and MUST have "Accumulated Depreciation" in its name — the Cash Flow generator excludes it from Investing by name). **`accounts.name` is UNIQUE — a parent header and its leaf must have different names.**

**New accounts to add** (code · name · account_type · classification · normal_balance · parent):

*Assets — Current*
- `10300` Inventories · Asset · Current · debit · (top-level)
  - `10301` Raw Materials Inventory · Asset · Current · debit · 10300
  - `10302` Work-in-Process Inventory · Asset · Current · debit · 10300
  - `10303` Finished Goods Inventory · Asset · Current · debit · 10300
  - `10304` Packaging Materials Inventory · Asset · Current · debit · 10300
- `10400` Prepaid Expenses · Asset · Current · debit · (top-level)
  - `10401` Prepaid Insurance · Asset · Current · debit · 10400
  - `10402` Prepaid Rent · Asset · Current · debit · 10400

*Assets — Non-Current (PPE)*
- `12000` Property, Plant & Equipment · Asset · Non-Current · debit · (top-level)
  - `12010` Machinery & Packing Equipment · Asset · Non-Current · debit · 12000
  - `12011` Accumulated Depreciation - Machinery · Asset · Non-Current · **credit** · 12000
  - `12020` Building & Leasehold Improvements · Asset · Non-Current · debit · 12000
  - `12021` Accumulated Depreciation - Building · Asset · Non-Current · **credit** · 12000
  - `12030` Office & Furniture Equipment · Asset · Non-Current · debit · 12000
  - `12031` Accumulated Depreciation - Office Equipment · Asset · Non-Current · **credit** · 12000
  - `12040` Delivery Vehicles · Asset · Non-Current · debit · 12000
  - `12041` Accumulated Depreciation - Vehicles · Asset · Non-Current · **credit** · 12000

*Liabilities — Current*
- `20302` Withholding Tax Payable - Compensation · Liability · Current · credit · **20300** (existing WHT parent)
- `20400` Accrued & Statutory Payables · Liability · Current · credit · (top-level)
  - `20401` Accrued Salaries & Wages · Liability · Current · credit · 20400
  - `20402` SSS Premiums Payable · Liability · Current · credit · 20400
  - `20403` PhilHealth Contributions Payable · Liability · Current · credit · 20400
  - `20404` Pag-IBIG Contributions Payable · Liability · Current · credit · 20400
  - `20405` Accrued Utilities · Liability · Current · credit · 20400
  - `20406` Income Tax Payable · Liability · Current · credit · 20400

*Liabilities — Non-Current*
- `25000` Loans Payable · Liability · Non-Current · credit · (top-level)
  - `25001` Bank Loan Payable · Liability · Non-Current · credit · 25000

*Equity*
- `30100` Share Capital · Equity · — · credit · (top-level)
  - `30101` Paid-in Capital · Equity · — · credit · 30100

*Revenue* — reuse existing `40101 Sales - Goods` as primary finished-goods revenue; add:
- `40200` Other Income · Other Income · — · credit · (top-level)
  - `40201` Scrap & By-product Sales · Other Income · — · credit · 40200
  - `40202` Interest Income · Other Income · — · credit · 40200

*Cost of Sales*
- `50000` Cost of Sales · Cost of Goods Sold · — · debit · (top-level)
  - `50001` Cost of Goods Sold · Cost of Goods Sold · — · debit · 50000

*Administrative Expenses*
- `60000` Administrative Expenses · Administrative Expense · — · debit · (top-level)
  - `60101` Salaries & Wages - Administrative · Administrative Expense
  - `60102` SSS/PhilHealth/Pag-IBIG - Employer Share · Administrative Expense
  - `60103` Rent Expense · Administrative Expense
  - `60104` Utilities Expense - Office · Administrative Expense
  - `60105` Office Supplies · Administrative Expense
  - `60106` Repairs & Maintenance · Administrative Expense
  - `60107` Depreciation Expense - Administrative · Administrative Expense
  - `60108` Professional Fees · Administrative Expense
  - `60109` Taxes & Licenses · Administrative Expense
  - `60110` Insurance Expense · Administrative Expense
  - `60111` Communication Expense · Administrative Expense
  (all · Administrative Expense · — · debit · 60000)

*Selling & Distribution Expenses*
- `61000` Selling & Distribution Expenses · Selling Expense · — · debit · (top-level)
  - `61101` Delivery & Freight-out · Selling Expense
  - `61102` Fuel & Oil · Selling Expense
  - `61103` Advertising & Promotions · Selling Expense
  - `61104` Depreciation Expense - Delivery Vehicles · Selling Expense
  (all · Selling Expense · — · debit · 61000)

*Other Expenses*
- `70000` Other Expenses · Other Expense · — · debit · (top-level)
  - `70101` Interest Expense · Other Expense · — · debit · 70000
  - `70102` Bank Charges · Other Expense · — · debit · 70000

*Income Tax*
- `80000` Income Tax Expense · Income Tax Expense · — · debit · (top-level)
  - `80101` Income Tax Expense - Current · Income Tax Expense · — · debit · 80000

≈ 55 new accounts (~78 total). Codes are for sorting only — FS placement is by `account_type`/`classification`, not prefix.

## Transaction model (GL-level manufacturing flow)

All money math reuses the **real posting helpers** (`_post_invoice_je` / `_post_ap_je` / `_post_crv_je` / `_post_cdv_je`) so seeded docs are byte-identical to hand-entered ones (VAT extraction inclusive; WHT per [[wht-net-of-rounded-vat-formula]]). Hand-built JEs use a shared `build_jv()` with an `is_balanced` guard.

1. **Opening (2024-01-01)** — company launch, one opening JV: Dr Cash, Dr Machinery/Building/Vehicles, Dr Raw Materials Inventory; Cr Paid-in Capital, Cr Bank Loan Payable. Establishes the opening Balance Sheet (fresh start → no prior Retained Earnings).
2. **Raw-material & packaging purchases** — AP bills (Input VAT), line account = `10301`/`10304`; paid via CDV. WHT applied on *service* purchases (rent 5%, professional 10%), not on goods.
3. **Production (monthly JV)** — capitalize factory costs into inventory: Dr `10303` Finished Goods; Cr `10301` Raw Materials (consumed), Cr `20401` Accrued Salaries (factory labor), Cr `12011` Accum Depr-Machinery (factory depreciation), Cr Cash/AP (factory utilities/overhead). Production posts directly RM→Finished Goods; `10302` Work-in-Process carries a modest month-end balance via an optional partial-completion JV (so the BS shows WIP), reversed the following month. **Factory costs never hit a P&L expense line — they inventory until sold.**
4. **Sales** — SI to food-brand customers for finished goods: Dr AR, Cr `40101` Sales - Goods, Cr Output VAT; customer withholds **1% EWT on goods** (→ `10212` CWT). Collections via CRV.
5. **COGS (per period)** — Dr `50001` Cost of Goods Sold, Cr `10303` Finished Goods.
6. **Payroll (monthly JV)** — admin salaries Dr `60101`; Cr `20401` Accrued Salaries, Cr `20402/3/4` statutory (employee share), Cr `20302` WT-Compensation. Employer share Dr `60102`, Cr statutory. Settled via CDV.
7. **Depreciation (monthly JV)** — admin/office Dr `60107`, vehicles Dr `61104`; Cr the matching `120x1` Accumulated Depreciation. (Factory depreciation is in the production JV, step 3.)
8. **Operating expenses** — rent, utilities, supplies, professional fees, insurance, taxes & licenses, freight, fuel, advertising — via AP/CDV or direct CDV, to the `60xxx`/`61xxx` accounts.
9. **Financing** — monthly bank-loan amortization (Dr `25001` principal + Dr `70101` Interest Expense, Cr Cash) via CDV/JV.
10. **Year-end close (2024, 2025)** — via the year-end module so Retained Earnings rolls; 2026 stays open. Income tax accrued at year-end: Dr `80101` Income Tax Expense - Current, Cr `20406` Income Tax Payable.

## Volume & cadence

Per month (≈30 months): 8–15 sales invoices, 10–20 purchases, matching CRV/CDV settlements, 1 production JV, 1 COGS JV, 1 payroll JV, 1 depreciation JV, 1 loan-amortization entry. Totals ≈ 300–450 SI, ≈ 350–500 AP, ≈ 150 JVs. Amounts scaled so the company is modestly profitable with realistic gross margin (~25–35%). Deterministic generation (seeded pseudo-random by index — no `Math.random`/wall-clock) for reproducible rebuilds.

## Architecture

- New module `app/seeds/food_demo.py`, entry `run_seed_food_demo(reset=False)`, mirroring `demo_seed.py`:
  - `seed_food_coa()` — idempotent COA build (preserve baseline, add the new accounts).
  - `seed_food_baseline()` — admin, MAIN branch, company settings, VAT/SalesVAT/WHT categories wired to the right accounts, periods opened Jan 2024→Jun 2026. Idempotent.
  - `seed_food_customers()` / `seed_food_vendors()` — food-brand customers; material/packaging/utility/landlord vendors.
  - opening JV, then the transaction generators (§ above).
- **Date-keyed doc numbering** rolled locally (built-in generators key on *today* → wrong for backdated docs); one `_docnum(prefix, doc_date, branch_id)` helper.
- **`is_balanced` guard** on every hand-built JE; **refuse-on-rerun** with a clear message (not idempotent).
- New CLI command `flask seed-food-demo` in `app/__init__.py` (alongside the existing seed commands).
- **Rebuild procedure:** confirm `.env` → `cas_demo.db` → delete `instance/cas_demo.db` → `flask db upgrade` → `flask seed-food-demo`.

## Testing

- **pytest** (temp DB): seeder runs; COA present with correct `account_type`/`classification`; **Trial Balance balances** (Σdr = Σcr); **Balance Sheet balances** (Assets = Liabilities + Equity); **zero unbalanced JEs**; doc numbers are period-correct (year/month match doc date); **refuse-on-rerun** works; Income Statement has non-zero Revenue, COGS, Gross Profit, and Operating Income (proves the rich `account_type`s classify).
- **Browser spot-check** (the past-year-invisible gotcha — pytest won't catch it): after seeding, the dashboard + transaction lists + reports under the **default (2026) filters** show populated data.

## Non-goals / constraints

- No perpetual inventory / production module, stock cards, or quantity tracking (CAS has none) — inventory is GL balances only.
- Seeded documents have **no audit-log rows** (the `_post_*_je` helpers don't log; audit lives in the view layer) — by design, matching `history_seed`/`demo_seed`.
- No app/model/migration changes — this is data generation only.
- Zhiyuan `seed-demo` is left untouched.
