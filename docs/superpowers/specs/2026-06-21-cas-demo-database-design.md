# CAS Demo Database — Zhiyuan Construction Corporation — Design

**Date:** 2026-06-21
**Status:** Approved (pending spec review)
**Related:** [[2026-06-21-ric-cas-database-separation-design]]

## Context

CAS now deploys as separate per-instance databases (RIC client → `ric.db`; CAS
demo → its own DB). This spec builds the **CAS demo database**: a self-contained,
reproducible dataset for client presentations, modelling a **fabricated PH
construction company, "Zhiyuan Construction Corporation."**

The demo must exercise every document workflow end-to-end (not just GL journals,
which is how the RIC migration is done): Sales Invoices (SI), Cash Receipts (CRV),
Accounts Payable (APV), Cash Disbursements (CDV), and Journal Vouchers (JV),
including **stockholder capital investments**.

The Excel file in `instance/uploads/trial_balance.xlsx` (a multi-currency services
company) is explicitly **out of scope** — owner decision 2026-06-21.

## Goals

1. A construction-flavored Chart of Accounts.
2. A refreshed/cleaned `seed_data.py` plus a new reproducible `flask seed-demo`.
3. Fabricated construction master data (customers + vendors).
4. ~50–58 posted transactions across SI/CR/AP/CD/JV for **Jan 1 – Jun 19, 2025**.
5. Stockholder investments recorded as opening equity entries.

## Hard constraint discovered (drives the COA)

All five document types post into one central GL pair — `JournalEntry` +
`JournalEntryLine` (`app/journal_entries/models.py`). Each module exposes a
`_post_*_je(doc, user_id)` helper that builds the balanced **draft** JE; posting
just promotes it to `status='posted'`. **The posting code hardcodes specific
account codes**, so the construction COA is "construction-flavored on top of a
fixed BIR skeleton." These codes MUST exist as active, postable (leaf) accounts:

| Code | Account | Used by |
|------|---------|---------|
| `10201` | Accounts Receivable – Trade | SI, CRV |
| `10212` | Creditable Withholding Tax Receivable | SI, CRV (when WHT > 0) |
| `10501–10504` | Input VAT (Capital Goods/Domestic/Services/Importation) | AP, CDV (per VAT category) |
| `20101` | Accounts Payable – Trade | AP, CDV |
| `20301` | Withholding Tax Payable – Expanded | AP, CDV (when WHT > 0) |
| `20401` | Output VAT Payable | SI, CRV (per Sales VAT category) |

## Key design decision — reuse the posting helpers

The seeder **reuses the existing `_post_*_je()` helpers** instead of
re-implementing GL math. Demo documents therefore post byte-identically to
UI-entered ones and inherit the validated WHT-net-of-rounded-VAT formula
(`[[wht-net-of-rounded-vat-formula]]`) for free. Posting a seeded document =
create header + lines in `draft` → call `_post_*_je(doc, admin_id)` → set
`doc.status='posted'` and `doc.journal_entry.status='posted'` → commit → audit.

## Architecture / units

The work decomposes into independent, separately-testable units:

1. **`seed_construction_coa()`** — builds the COA (Appendix A). Two-pass
   (accounts, then parent links), mirroring the existing seeders.
2. **`seed_demo_reference()`** — company settings (Zhiyuan profile), Main Branch,
   admin, VAT categories, Sales VAT categories, WHT codes (incl. **WC120**),
   open `AccountingPeriod` rows for 2025 Jan–Jun.
3. **`seed_demo_master_data()`** — fabricated customers + vendors (Appendix B).
4. **`seed_demo_transactions()`** — generates the documents (Appendix C) by
   reusing the posting helpers; wires CRV→SI and CDV→AP applications.
5. **`flask seed-demo` CLI** — orchestrates 1→4.

The **baseline + master-data** units are idempotent (skip-by-code), so re-running
them is safe. The **transaction** unit is NOT idempotent — invoice/AP numbers are
`UNIQUE`, so it builds the document set exactly once. `seed-demo` is therefore a
**build-into-a-clean-DB** command: if demo transactions already exist it refuses
with a clear message rather than duplicating. Rebuild = delete the DB file →
`flask db upgrade` → `flask seed-demo`. With a fixed RNG seed, a from-clean run
reproduces the demo deterministically.

> Note (accepted, not fixed): the auto-created transactional journal entries are
> numbered by the shared `generate_entry_number()`, which keys on the *run* year
> (`JE-<run-year>-####`), while document numbers and `entry_date` are correctly
> 2025 and the JVs read `JV-2025-MM-####`. Making JE numbers date-aware would
> change a helper shared by all four modules; left as-is for the demo.

## Reference data

- **VAT (input):** `V12CG`/`V12DG`/`V12SV`/`V12IM` (12%, wired to 10501–10504),
  `V0`/`VEX`/`INV` (0%) — same set as `seed_minimal`.
- **Sales VAT (output):** `V12` (12%, wired to 20401), `V0`, `VEX`.
- **WHT codes:** `WC120` Contractors/Subcontractors 2% (**headline for
  construction**), `WC158` Goods 1%, `WC160` Services 2%, `WC100` Rentals 5%,
  `WC010` Professional Fees 10%. `WC120`/`WC158`/`WC160` get `sales_name` set
  (the company is a contractor → clients withhold `WC120` on its billings).

## Master data (fabricated)

- **~7 customers** — project owners/developers (Appendix B). Mix VAT / non-VAT
  (one individual homeowner non-VAT).
- **~10 vendors** — material suppliers, subcontractors, utilities, professional
  services (Appendix B), each tagged with a default WHT (subcons→WC120,
  materials→WC158, rentals→WC100, prof fees→WC010).

## Transactions — Jan 1 – Jun 19, 2025 (~50–58 docs)

Light volume, spread across the six months. All posted.

- **Stockholder investments (3 JV, `entry_type='opening'`, early Jan):** three
  stockholders inject capital — two cash (Dr Cash in Bank / Cr Capital Stock +
  Additional Paid-in Capital), one in-kind (Dr Construction Equipment / Cr
  Capital Stock). Stockholder names recorded in the JV description (CAS has no
  stockholder entity; equity is tracked via accounts).
- **SI (~10):** progress billings to project owners, VATable 12%, client
  withholds `WC120` 2%.
- **AP (~10):** materials (`WC158`), subcontractor billings (`WC120`), equipment
  rental (`WC100`), professional fees (`WC010`); 12% input VAT; `vendor_invoice_*`
  set (required when VAT/WHT > 0).
- **CRV (~9):** mostly collections applied to posted SIs; 1–2 direct revenue
  (equipment rental income).
- **CDV (~9):** mostly payments applied to posted APs; a few direct expenses
  (Meralco, fuel, supplies).
- **JV (~8):** the 3 investments + monthly depreciation, an accrual, a
  reclassification, one reversal example.

Sequencing: investments → SIs/APs → CRVs (collect SIs) / CDVs (pay APs) → period
adjustment JVs, so applications reference already-posted documents.

## Build / rollout mechanism

1. **Target DB:** a fresh `instance/cas_demo.db`. Temporarily point `.env`
   `SQLALCHEMY_DATABASE_URI=sqlite:///cas_demo.db`, run `flask db upgrade`, then
   build. **`ric.db` is never touched**; restore `.env` to `ric.db` afterward.
   The `.env`-aware `/reset-database` guard protects RIC.
2. **Baseline first:** run units 1–3 (COA, reference, master data) into
   `cas_demo.db`.
3. **UI validation (owner):** run the dev server on `cas_demo.db` and enter **2–5
   sample documents per type** (SI/CR/AP/CD/JV) through the UI. Owner eyeballs
   shape/amounts/posting. Findings feed back into the generator.
4. **Full seed:** finalize and run `seed_demo_transactions()` to produce the
   complete set. The transaction generator is **not** idempotent (unique doc
   numbers), so it runs once against a clean DB; `seed-demo` refuses if demo
   transactions already exist. Authoritative rebuild = delete `cas_demo.db` →
   `flask db upgrade` → `flask seed-demo` (deterministic via fixed RNG seed). Any
   UI validation samples entered earlier are discarded by this clean rebuild.
5. **`seed_data.py` refresh:** reconcile/clean existing seeders while adding the
   demo seeders (no behavior change to `seed-db`/`seed-minimal` beyond cleanup).

## Testing

- Per-unit tests: COA seeded (counts, magic codes present + postable), reference
  data present, master data created, periods open.
- Transaction tests: each document type posts; linked JE is balanced and
  `status='posted'`; CRV reduces SI balance; CDV reduces AP balance.
  (Note: the seeder posts via the `_post_*_je` helpers, not the view routes, so
  it writes **no audit rows** — consistent with the existing `history_seed.py`
  convention. The CLAUDE.md "verify the audit log in CRUD tests" rule applies to
  the view-layer CRUD, not to batch seeders.)
- A trial-balance assertion: after full seed, total debits == total credits
  across posted `JournalEntryLine`s.

## Out of scope

- `trial_balance.xlsx` / the services company.
- A stockholder master-data entity (equity tracked via accounts only).
- Items/inventory module, manufacturing, multi-branch (single Main Branch).
- Deploying the demo server itself (separate task).

## Rollback

`cas_demo.db` is a standalone new file; deleting it and restoring `.env` to
`ric.db` fully reverts. No change to `ric.db` or production seeders' behavior.

---

## Appendix A — Construction Chart of Accounts

Magic/required codes marked ★ (must stay postable). Headers (parents) are
non-postable; hierarchy is derived from `parent_id`.

**Assets (1xxxx)**
- 10101 Cash on Hand
- 10102 Petty Cash Fund
- 10111 Cash in Bank – Current Account
- 10112 Cash in Bank – Savings Account
- ★10201 Accounts Receivable – Trade
- 10203 Retention Receivable
- 10210 Advances to Subcontractors/Suppliers
- ★10212 Creditable Withholding Tax Receivable
- 10301 Construction Materials Inventory
- 10310 Construction in Progress (CIP)
- 10500 Input VAT *(header)*
  - ★10501 Input VAT – Capital Goods
  - ★10502 Input VAT – Domestic Goods
  - ★10503 Input VAT – Services
  - ★10504 Input VAT – Importation
- 11110 Construction Equipment
- 11111 Accumulated Depreciation – Construction Equipment
- 11120 Vehicles
- 11121 Accumulated Depreciation – Vehicles
- 11130 Tools and Small Equipment
- 11131 Accumulated Depreciation – Tools and Small Equipment
- 11140 Office Equipment
- 11141 Accumulated Depreciation – Office Equipment

**Liabilities (2xxxx)**
- ★20101 Accounts Payable – Trade
- 20110 Subcontractors Payable
- 20120 Retention Payable
- 20300 Withholding Tax Payable *(header)*
  - ★20301 Withholding Tax Payable – Expanded
  - 20302 Withholding Tax Payable – Compensation
- ★20401 Output VAT Payable
- 20420 Statutory Payables *(header)*
  - 20421 SSS Premiums Payable
  - 20422 PhilHealth Contributions Payable
  - 20423 Pag-IBIG Contributions Payable
- 20430 Billings in Excess of Costs
- 21101 Loans Payable

**Equity (3xxxx)**
- 30101 Capital Stock
- 30102 Additional Paid-in Capital
- 30103 Subscriptions Receivable *(contra, debit)*
- 30201 Retained Earnings
- 30301 Current-Year Earnings

**Revenue (4xxxx)**
- 40101 Construction Contract Revenue
- 40102 Service Income
- 40103 Materials Sales
- 40201 Equipment Rental Income
- 40202 Interest Income
- 40203 Miscellaneous Income

**Cost of Construction (5xxxx)**
- 50100 Cost of Construction *(header)*
  - 50101 Direct Materials
  - 50102 Direct Labor
  - 50103 Subcontractor Costs
  - 50104 Equipment Rental Expense
  - 50105 Permits and Project Fees
  - 50106 Project Overhead

**Operating Expenses (5xxxx)**
- 50200 Operating Expenses *(header)*
  - 50210 Salaries and Wages
  - 50211 Employee Benefits (SSS/PhilHealth/Pag-IBIG)
  - 50220 Rent Expense
  - 50221 Utilities – Electricity
  - 50222 Utilities – Water
  - 50223 Communications
  - 50230 Office Supplies Expense
  - 50240 Professional Fees
  - 50250 Taxes and Licenses
  - 50260 Depreciation Expense
  - 50270 Repairs and Maintenance
  - 50280 Fuel and Oil
  - 50290 Representation and Entertainment
  - 50298 Miscellaneous Expense
- 50300 Financial Expenses *(header)*
  - 50301 Interest Expense
  - 50302 Bank Charges

## Appendix B — Master data (fabricated)

**Customers (~7)**
1. Vista Land Estates Inc. — VAT, WC120
2. Megabuild Properties Corp. — VAT, WC120
3. St. Luke's Realty Development Corp. — VAT, WC120
4. Ayala Township Development Inc. — VAT, WC120
5. Robinsons Land Corporation — VAT, WC120
6. Greenfield District Devt Corp. — VAT, WC120
7. Juan dela Cruz (private homeowner) — non-VAT, no WHT

**Vendors (~10)**
1. Holcim Philippines Inc. (cement) — VAT, WC158
2. SteelAsia Manufacturing Corp. (rebar) — VAT, WC158
3. Wilcon Depot Inc. (hardware) — VAT, WC158
4. Premier Electrical Subcontractor — VAT, WC120
5. Reliable Plumbing & Sanitary Subcon — VAT, WC120
6. Manila Equipment Rentals Inc. — VAT, WC100
7. Meralco (utility) — VAT, WC100
8. Petron Corporation (fuel) — VAT, WC158
9. Cruz & Associates Law Office — VAT, WC010
10. Pioneer Insurance & Surety Corp. — VAT, WC160

(Exact TINs/addresses are fabricated demo values, finalized in the seeder.)

## Appendix C — Transaction outline

Concrete amounts/dates finalized in the generator; counts and shapes per the
Transactions section above. Realism rules: SIs use Construction Contract Revenue
(40101) with V12 + WC120; material APs use Direct Materials (50101)/CIP with
V12DG + WC158; subcontractor APs use Subcontractor Costs (50103) with V12SV +
WC120; CRVs apply to SIs via AR; CDVs apply to APs; depreciation JVs hit 50260 /
accumulated-depreciation accounts.
