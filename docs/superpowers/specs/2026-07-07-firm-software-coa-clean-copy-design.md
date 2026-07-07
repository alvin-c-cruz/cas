# Clean Copy — Combined Accounting Firm + Software Company (design)

**Date:** 2026-07-07
**Status:** Approved (brainstorming) — pending spec review
**Owner:** alvin (deploying to own PythonAnywhere account `alvinccruz`)

## Goal

Stand up a **fresh, clean CAS instance** for the user's own use — a combined
**professional-services accounting firm + software company** — with a purpose-built
Chart of Accounts, PH VAT + EWT master data, and placeholder identity, then deploy it
to the user's PythonAnywhere account at `alvinccruz.pythonanywhere.com`.

This is the user's **own** instance (alvin = the developer), so the client
IP-containment posture from the RIC deployment does **not** apply.

## Non-goals

- No schema/model changes. This is data + a new seed command only.
- No new UI. Everything is renameable in-app after seeding.
- No sample transactions — clean books, zero journal entries.

## Approach

Add a new, tested Flask CLI command **`flask seed-firm`** and a COA data module
`app/seeds/firm_coa.py` (`FIRM_COA`), mirroring the existing `manufacturing_coa.py` /
`seed_minimal` pattern. `seed-firm` produces a clean DB identical in shape to
`seed-minimal` (admin, branch, settings, VAT/EWT) but with:

1. `FIRM_COA` instead of `BASELINE_COA`, and
2. `company_name = 'Cruz Accounting & Software'` (placeholder) instead of `'Company Name'`.

Reproducibility is the point: build + verify locally, commit to CAS `main`, then on
PythonAnywhere run the *same* `flask seed-firm` against a fresh DB — no manual entry.

### Light refactor (keeps `seed_minimal` output identical)

Extract module-level helpers in `app/seeds/seed_data.py` so both commands share code:

- `_seed_admin_and_branch()` — admin (`admin`/`admin123`) + `MAIN` branch (unchanged).
- `_seed_app_settings(company_name)` — the 24-row settings block, `company_name`
  parameterized (default `'Company Name'`).
- `_seed_accounts(coa_list)` — the two-pass create-then-wire-parent loop.
- `_seed_vat_categories()`, `_seed_sales_vat_categories()`, `_seed_withholding_taxes()`
  — verbatim from `seed_minimal` (identical data; the firm COA keeps codes
  `10501–10504` / `20201`, so the VAT pointers resolve unchanged).

`seed_minimal()` becomes a thin caller of these with `BASELINE_COA` /
`'Company Name'`; `seed_firm()` calls them with `FIRM_COA` /
`'Cruz Accounting & Software'`. A regression test asserts `seed_minimal` still yields
the same 25 accounts + 7/3/8 VAT/EWT rows so `/reset-database` is unaffected.

Both are registered as CLI commands in `app/__init__.py` next to `seed-db` / `seed-minimal`.

## Invariants (must hold — the posting engine hardcodes these)

Six "magic" account codes are looked up by `Account.query.filter_by(code=...)` and MUST
exist (as leaves that can receive programmatic JE legs), at their exact codes:

| code | role |
|---|---|
| `10201` | Accounts Receivable - Trade (SI/CRV AR leg) |
| `10212` | Creditable Withholding Tax (SI/CRV, WHT-receivable fallback) |
| `20101` | Accounts Payable - Trade (AP/CDV) |
| `20301` | Withholding Tax Payable - Expanded (AP/CDV, WHT-payable fallback) |
| `30201` | Retained Earnings - Unappropriated (year-end close) |
| `30301` | Current Year Earnings (year-end close income summary) |

VAT accounts are **not** hardcoded in posting — they resolve through each VAT category's
`input_vat_account_id` / `output_vat_account_id`. `FIRM_COA` keeps `10501–10504`
(input) and `20201` (output) so the seeded pointers resolve.

**Design rule — single AR:** the SI/CRV engine posts AR only to `10201`, so there is
**one** `Accounts Receivable - Trade`. Business-line separation lives on the **revenue**
side (distinct income accounts), which is where segment reporting actually surfaces.

## Chart of Accounts — `FIRM_COA` (authoritative)

Fields: `code`, `name` (UNIQUE), `type` (FS taxonomy), `classification`
(Current/Non-Current for Asset/Liability, else None), `normal_balance`, `parent`
(parent CODE or None = top-level group). Hierarchy is derived; a node is a
non-postable **group** if top-level or has children, else a postable **leaf**.
★ = required magic code.

### ASSETS — Current (Asset / Current / debit)
- `10100` Cash and Cash Equivalents *(group)*
  - `10101` Cash on Hand
  - `10102` Petty Cash Fund
  - `10110` Cash in Bank - Current Account
  - `10111` Cash in Bank - Savings Account
- `10200` Trade and Other Receivables *(group)*
  - `10201` **★ Accounts Receivable - Trade**
  - `10202` Allowance for Doubtful Accounts *(normal_balance: credit — contra)*
  - `10210` Advances to Employees
  - `10211` Advances to Officers
  - `10212` **★ Creditable Withholding Tax**
- `10400` Prepaid Expenses and Other Current Assets *(group)*
  - `10401` Prepaid Rent
  - `10402` Prepaid Insurance
  - `10403` Prepaid Software Subscriptions
  - `10404` Other Current Assets
- `10500` Input VAT *(group)*
  - `10501` Input VAT - Capital Goods
  - `10502` Input VAT - Domestic Goods
  - `10503` Input VAT - Services
  - `10504` Input VAT - Importation

### ASSETS — Non-Current (Asset / Non-Current / debit)
- `11100` Property and Equipment *(group)*
  - `11110` Office Equipment
  - `11111` Accumulated Depreciation - Office Equipment *(credit — contra)*
  - `11120` Computer Equipment
  - `11121` Accumulated Depreciation - Computer Equipment *(credit — contra)*
  - `11130` Furniture and Fixtures
  - `11131` Accumulated Depreciation - Furniture and Fixtures *(credit — contra)*
  - `11140` Leasehold Improvements
  - `11141` Accumulated Depreciation - Leasehold Improvements *(credit — contra)*
- `11200` Intangible Assets *(group)*
  - `11201` Capitalized Software Development Costs
  - `11202` Accumulated Amortization - Software Development Costs *(credit — contra)*
  - `11203` Software and Licenses
  - `11204` Accumulated Amortization - Software and Licenses *(credit — contra)*
- `11300` Other Non-Current Assets *(group)*
  - `11301` Security Deposits

### LIABILITIES — Current (Liability / Current / credit)
- `20100` Trade and Other Payables *(group)*
  - `20101` **★ Accounts Payable - Trade**
  - `20102` Accounts Payable - Others
  - `20103` Accrued Expenses
  - `20104` Accrued Salaries and Wages
- `20200` Output VAT *(group)*
  - `20201` Output VAT - Sales
  - `20202` VAT Payable
- `20300` Withholding and Other Taxes Payable *(group)*
  - `20301` **★ Withholding Tax Payable - Expanded**
  - `20302` Withholding Tax Payable - Compensation
  - `20303` Income Tax Payable
- `20400` Statutory Payables *(group)*
  - `20401` SSS Contributions Payable
  - `20402` PhilHealth Contributions Payable
  - `20403` Pag-IBIG Contributions Payable
- `20500` Unearned and Deferred Revenue *(group)*
  - `20501` Unearned Subscription Revenue
  - `20502` Unearned Service Revenue

### LIABILITIES — Non-Current (Liability / Non-Current / credit)
- `21100` Long-Term Liabilities *(group)*
  - `21101` Loans Payable
  - `21102` Lease Liability

### EQUITY (Equity / None / credit unless noted)
- `30100` Owners' Equity *(group)*
  - `30101` Owners' Capital
  - `30102` Owners' Drawings *(debit — contra)*
- `30200` Retained Earnings *(group)*
  - `30201` **★ Retained Earnings - Unappropriated**
- `30301` **★ Current Year Earnings** *(top-level; used only by year-end close)*

### REVENUE
- `40100` Accounting Services Revenue *(group, Revenue)*
  - `40101` Bookkeeping Fees
  - `40102` Audit and Assurance Fees
  - `40103` Tax Compliance Fees
  - `40104` Advisory and Consulting Fees
- `40200` Software Revenue *(group, Revenue)*
  - `40201` Subscription (SaaS) Revenue
  - `40202` Software License Revenue
  - `40203` Custom Development Revenue
  - `40204` Support and Maintenance Revenue
  - `40205` Implementation and Setup Revenue
- `40300` Other Income *(group, Other Income)*
  - `40301` Interest Income
  - `40302` Miscellaneous Income

### COST OF SERVICES (Cost of Goods Sold / debit)
- `50100` Cost of Accounting Services *(group)*
  - `50101` Salaries - Professional Staff
  - `50102` Direct Engagement Costs
- `50150` Cost of Software Services *(group)*
  - `50151` Salaries - Developers
  - `50152` Cloud Hosting and Infrastructure
  - `50153` Third-Party Software and API Costs
  - `50154` Amortization - Capitalized Software Development

### SELLING EXPENSE (Selling Expense / debit)
- `50210` Selling and Marketing Expenses *(group)*
  - `50211` Advertising and Marketing
  - `50212` Representation and Entertainment
  - `50213` Sales Commissions

### ADMINISTRATIVE EXPENSE (Administrative Expense / debit)
- `50220` General and Administrative Expenses *(group)*
  - `50221` Salaries and Wages - Administrative
  - `50222` SSS, PhilHealth and Pag-IBIG - Employer Share
  - `50223` 13th Month Pay and Other Benefits
  - `50224` Rent Expense
  - `50225` Utilities Expense
  - `50226` Communications and Internet Expense
  - `50227` Office Supplies Expense
  - `50228` Software Subscriptions - Internal Tools
  - `50229` Depreciation Expense
  - `50230` Amortization Expense
  - `50231` Insurance Expense
  - `50232` Taxes and Licenses
  - `50233` Professional Fees
  - `50234` Transportation and Travel
  - `50235` Training and Seminars
  - `50236` Repairs and Maintenance
  - `50237` Bank Charges
  - `50238` Bad Debts Expense
  - `50239` Miscellaneous Expense

### OTHER EXPENSE (Other Expense / debit)
- `50300` Other Expenses *(group)*
  - `50301` Interest Expense
  - `50302` Loss on Disposal of Assets

### INCOME TAX EXPENSE (Income Tax Expense / debit)
- `50400` Income Tax Expense *(group)*
  - `50401` Income Tax Expense - Current

## VAT / EWT master data (reused verbatim from `seed_minimal`)

- **Input VAT categories (7):** `VEX`, `V0`, `INV` (rate 0); `V12CG`→`10501`,
  `V12DG`→`10502`, `V12SV`→`10503`, `V12IM`→`10504` (rate 12).
- **Sales VAT categories (3):** `V12` (regular, →`20201`), `V0` (zero_export),
  `VEX` (exempt).
- **EWT codes (8):** `WC158`/`WI158` goods 1%; `WC160`/`WI160` services 2%;
  `WC100`/`WI100` rentals 5%; `WC010` professional-corp 10%; `WI010` professional-indiv 5%.
  All resolve to `20301` (payable) / `10212` (receivable) via the model's NULL fallback.
  These cover both directions: clients withholding on the firm's professional fees
  (→ CWT receivable `10212`) and the firm withholding from vendors (→ `20301`).

## Identity

- `company_name = 'Cruz Accounting & Software'` (placeholder — renameable in-app).
- Branch `MAIN` / `Main Branch` / `Head Office`.
- `vat_registration_type = VAT`; other identity fields blank.
- Admin `admin` / `admin123` (change post-deploy).

## Testing (TDD)

New `tests/unit/test_firm_coa.py` (+ a firm-seed integration test), asserting:

1. **No duplicate codes** and **no duplicate names** in `FIRM_COA` (`Account.name` is UNIQUE).
2. **Every `parent` reference resolves** to a code present in the list.
3. **All six magic codes present** with correct type/normal_balance.
4. **Every parent-code group has ≥1 child**; every account with children is a group;
   the magic leaves `10201/10212/20101/20301/30201` are leaves (have a parent) so they
   are postable. (`30301` is intentionally top-level — close writes to it programmatically.)
5. **FS-taxonomy validity:** every `type` ∈ the allowed `account_types` sets;
   Asset/Liability carry a `classification`, others `None`; contra accounts carry the
   opposite normal balance.
6. **Seed integration:** running `seed_firm()` on an empty test DB creates the full COA
   + 7/3/8 VAT/EWT rows; each VAT category's account pointer resolves; `company_name`
   == placeholder; books have zero JE and balance trivially.
7. **`seed_minimal` unchanged:** after the refactor, `seed_minimal()` still yields the
   original 25 `BASELINE_COA` accounts and `company_name == 'Company Name'`.

Run targeted pytest locally; `/run-tests` and `/guard` are user-triggered.

## Deployment plan (PythonAnywhere `alvinccruz`, driven via Chrome MCP)

Prereqs the user provides live: PA login (Chrome signed into `alvinccruz`), a real
`SECRET_KEY`, and (optional, for email) a Gmail app password for `alvinccruz12@gmail.com`.

1. Commit `firm_coa.py` + `seed-firm` + tests to CAS `main`; push to
   `github.com/alvin-c-cruz/cas.git` (user says "push").
2. PA **Bash console:** `git clone` (or `pull`) the CAS repo into the `alvinccruz` account.
3. Create/activate a virtualenv; `pip install -r requirements.txt` **plus
   `python-dateutil`** (real runtime dep missing from `requirements.txt` — RIC gotcha).
4. Write `.env` on PA: `SECRET_KEY`, `FLASK_ENV=production`,
   `SQLALCHEMY_DATABASE_URI=sqlite:///<home>/cas.db`, mail settings if used.
5. `flask db upgrade` (build schema), then **`flask seed-firm`** (clean firm COA).
6. **Web tab:** point the WSGI file at `wsgi.py`; set `PYTHONANYWHERE_USERNAME`;
   **append `ProxyFix`** to the WSGI app (RIC gotcha — prod HTTPS-enforce loops without it).
7. Reload the web app; verify login at `alvinccruz.pythonanywhere.com`, confirm the COA
   renders, and change the admin password.

## Open risks

- PA free-tier auto-disables monthly and blocks custom domains (RIC note) — fine for now.
- `Account.name` UNIQUE: the account list is pre-checked in tests before any deploy.
- Refactor blast radius on `seed_minimal` / `/reset-database` — pinned by test (7) above.
