# CAS — Project Status

_Last updated: 2026-09-03 · Branch: `main` (clean, in sync with `origin/main`, head `b2f9cef6`)_

CAS (Computerized Accounting System) — an accounting-first ERP for Philippine SMEs, BIR-compliant.
Flask 3.1 + SQLAlchemy 2.0 + SQLite, app-factory + blueprints, double-entry core, multi-branch,
role-based access, approval workflows, full audit trail. One database file per instance
(`cas.db`, `ric.db`, `cas_demo.db`).

---

## Deployment

Hosted on PythonAnywhere under the account **`philgenbooks2023`**
(https://www.pythonanywhere.com/user/philgenbooks2023/). `wsgi.py` loads `.env` by absolute path
(the WSGI working directory is unpredictable) and wraps the app in `ProxyFix(x_proto=1, x_host=1)`
so Flask sees the reverse proxy's HTTPS and `enforce_https()` does not redirect in a loop.

`wsgi.py:17` sets `PYTHONANYWHERE_USERNAME = 'philgenbooks2023'`, giving a `project_home` of
`/home/philgenbooks2023/cas` for both the `sys.path` entry and the `.env` path. (This was
`alvinccruz` until 2026-09-03 and did not match the live account.)

> ⚠️ The username is a **hardcoded constant**, so this file is correct for exactly one account.
> `.env.example` describes several instances of this codebase (RIC client, CAS demo) — any other
> deployment needs its own value here. A wrong value means the app cannot import or cannot find
> its `.env`. Deriving `project_home` from `Path.home()` would remove the constant entirely; not
> done, as PythonAnywhere keeps the live WSGI file outside the project directory.

---

## Running it locally

**A fresh clone does not boot.** There is no `.env` and no `*.db` in the tree, and `config.py:12`
raises if `SECRET_KEY` is unset. To bring an instance up:

```
cp .env.example .env          # then set a real SECRET_KEY
flask db upgrade
flask seed-db                 # or seed-demo / seed-minimal / seed-manufacturing / ...
python flask_app.py           # port 5050 by default; use_reloader=False
```

Tests are unaffected — `tests/conftest.py:51` injects its own key.

---

## Scale

| | |
|---|---|
| Python | ~203,000 lines across 1,413 files |
| Blueprints · routes · templates | 57 · 536 · 284 |
| Models · tables · migrations | 59 model files · 107 tables · 154 revisions (single alembic root) |
| Tests | 850 files · 6,587 collected (90 `e2e` deselected by default) |
| History | 2026-05-31 → 2026-09-02 · ~2,120 commits since the last status update |

Commit volume by month: Jun 1,134 · Jul 1,194 · Aug 375 · Sep 12.

---

## Module status

56 gated modules in `app/users/module_access.py::MODULE_REGISTRY`, each mapped to its sidebar item
and route prefixes. **Core** modules are always on. **Optional** modules are per-instance packaged
and per-user grantable (`default_enabled=False`); when not part of an instance's package they
return 404 for *every* role, admin included, so the route appears not to exist.

### Transactions

| Area | Core | Optional |
|---|---|---|
| Sales | Sales Invoices, Cash Receipts | Quotations, Sales Orders, Job Order Slips, Delivery Receipts, Credit Memos, Debit Notes |
| Purchases | Accounts Payable, Cash Disbursements | Purchase Requisitions, Purchase Orders, Receiving Reports, Vendor Debit Memos, Vendor Credit Memos |
| Accounting | Journal Voucher | — |
| Banking | — | Bank Accounts, Bank Transfers, Petty Cash, Bank Reconciliation |
| Payroll | — | Payroll |
| Inventory | — | Stock Adjustments |
| Manufacturing | — | Bill of Materials, Work Orders, Production Runs |
| Fixed Assets | — | Depreciation, Disposal |

### Ledger, reports and maintenance

| Section | Core | Optional |
|---|---|---|
| Ledger | Opening Balances, Chart of Accounts, General Ledger, Books of Accounts, Aging of AR (+ All Branches), Statement of Account, Aging of AP | — |
| Financial Reports | Income Statement, Balance Sheet, Cash Flow, Trial Balance, Accounting Periods, Year-End Close | IS by Product Line, Sales by Product Line, Budget Entry |
| Compliance | — | BIR Reports |
| Maintenance | Customers, Vendors | Products, Product Categories, Units of Measure, Inventory (Item Costing), Employees, Fixed Assets, Work Centers, Manufacturing Departments, Expense Allocation Rules |

Everything the previous status doc listed as "⏳ Coming soon" — General Ledger, Aging of AR, all
four financial statements, VAT reports, withholding tax — is now built. **Annual ITR is the only
remaining stub** in the whole app (`app/templates/base.html:1258`, a `Soon` badge pointing at
`dashboard.under_development`).

---

## Release tracks delivered since the last update

| Track | Scope |
|---|---|
| R-02 | AP variance snapshot + persisted variance badge |
| R-03 | Inventory: physical count, FIFO / specific-ID / LIFO costing, stock ledger + drill-down |
| R-04 | Banking: bank reconciliation, petty cash (true imprest) |
| R-05 | Fixed-asset depreciation runs |
| R-07 | Manufacturing: BOM, work orders (discrete), production runs (process), cost of production |
| R-08 | BIR filings foundation: VAT transaction-nature, WHT `tax_type`, unclassified never guessed |
| R-09 | Budgeting: budget entry + budget-vs-actual variance report |
| R-11 | Users/branches polish: email editing, branch colour themes |
| R-12 | VAT settlement engine (keystone) |

---

## Architecture notes

**Posting seam** — `app/posting/` holds two keyword-parameterized primitives,
`group_tax_buckets()` and `reconcile_buckets_to_total()` (`buckets.py:25,68`), shared by all six
posting paths (AP, CDV, CRV, SI, sales memos, purchase memos). The reconciliation tail — absorbing
the rounding difference into the largest bucket so booked legs tie to the header — is where the
R1 CRV/AP withholding-override money bugs lived. The extraction was deliberately behaviour-preserving,
not harmonizing; see the docstring at `buckets.py:8-18`.

**Control accounts** — `app/posting/control_accounts.py` resolves ~35 control keys from Company
Settings, **fail-closed with no guessed default** (`ControlAccountError` carries a "assign it in
Company Settings → Control Accounts" message so posting views' existing `except ValueError` flashes
rather than 500s). Only four legacy codes survive, and only for seeds/migrations/tests.

**BIR permanence** — there is **no journal-entry edit route** (`app/journal_entries/views.py` has
create/view/print/post/cancel/delete only); delete is draft-only (`views.py:368`) and cancel
re-validates the period is open. Posted vouchers cancel/void by posting a **reversal JE**, and the
source JE deliberately stays `posted` so the GL nets to zero with both entries visible in the books
(`app/accounts_payable/views.py:1677`).

**Amendments** — `app/amendments/` is an append-only `DocumentRevision` log (revision 0 is a
reserved baseline slot for the document as approved, never backfilled; rows are never updated or
deleted). Adopted by Purchase Orders and Purchase Requests only; Sales Orders still carry their own
`app/sales_orders/revisions.py`, the reference implementation this was generalized from.

**Integrity** — `flask integrity-check` (`app/integrity/`) runs four checks: every posted JE
balances, global trial balance nets to zero, no orphaned JE lines, every posted CDV/CRV has a valid
`journal_entry_id`. Exit 0/1; intended as a deploy pre-flight.

**VAT settlement** — `app/vat_settlement/service.py:93` computes each quarterly figure twice (a
balance as-of quarter end and a posted movement within the quarter) and **aborts if they diverge**,
which catches a backdated entry or a VAT account remapped after posting.

---

## BIR / reports coverage

**Implemented:** Trial Balance, Income Statement, Balance Sheet, Cash Flow (all with print + Excel
siblings) · all six books of accounts (General Journal, General Ledger, Sales, Purchase, Cash
Receipts, Cash Disbursements — assembled by reusing the `app/journals/*_journal_data.py` builders)
· SLS (Annex A), SLP (Annex B), Alphalist / 1601-EQ QAP, 2307 facsimile · **2550Q** worksheet,
box-numbered facsimile and Excel export · 1601-C · SSS / PhilHealth / Pag-IBIG remittance reports.

**Gaps:**

- **Annual ITR** — stubbed (`Soon` badge, no route).
- **2306** and **1601-FQ** — final withholding tax is captured in the data model
  (`WithholdingTax.tax_type == 'final'`) but has no form; noted at
  `app/withholding_tax/models.py:6-8`.
- **SAWT** — named as a target in `app/reports/wht_lines.py:6` but has no route.
- **1604-C / 1604-E** annual alphalists — no references anywhere in the codebase.

---

## Test health

- **Collection is clean:** 6,587 tests collected, 90 deselected (`e2e`), **0 collection errors** —
  every module imports.
- **Full-suite pass/fail has not been measured on this checkout.** The last recorded number
  (2,653 passed / 1 pre-existing failure) predates ~2,000 commits and is not current.
- `pytest-xdist` is listed in `requirements.txt` but is **not installed** in the current
  environment, so `-n auto` fails with `unrecognized arguments: -n`. Install it before relying on
  parallel runs — and pair it with occasional single-threaded runs, since `-n auto` can mask
  test-ordering and isolation bugs (see the note in `pytest.ini`).
- Run: `pytest` (default, excludes e2e) · `pytest -m e2e` (needs
  `python -m playwright install chromium`) · coverage is opt-in, not in `addopts`.

---

## Resolved since the last update

Every item the previous status doc listed as a high-priority open bug has been fixed; verified
against the current tree:

| Was | Now |
|---|---|
| BUG-SEC-01 no login rate-limit / lockout | `@limiter.limit('10 per minute; 50 per hour')` on login (`app/users/views.py:174`) + 5-attempt / 15-minute account lockout (`:84`) |
| BUG-SEC-02 failed login returns 200 | Returns **401** (`app/users/views.py:71,104,113`) |
| BUG-SEC-03 CSRF cookie not HttpOnly | Moot — no CSRF cookie is configured anywhere; Flask-WTF is session-based |
| BUG-02 VAT/WHT dropdowns empty in SI lines | Populated from the dedicated `sales_vat_categories` module (`app/sales_invoices/views.py:1064,1079`) |
| BUG-10 seeded COA missing AR / Revenue / Cash-in-Bank | Present — `10110` Cash in Bank, `10201` AR-Trade, `40100` Sales Revenue (`app/seeds/seed_data.py:141,147,242`) |
| BUG-13 AP voucher Description not visible | Description input present in AP line items (`app/accounts_payable/templates/accounts_payable/form.html:551`) |
| BUG-15 SI JE preview shows description in Account Title | Uses the account name (`.../sales_invoices/form.html:969`) |
| Global error handlers disabled in `create_app` | Re-enabled for non-debug (404/403/500/Exception, `app/__init__.py:788`); dev and tests keep raw tracebacks. CSRF and 429 handlers are active in all environments |
| `initSearchSelect` name collision | Resolved — one definition (`app/static/search-select.js:38`) |
| `/docs/` gitignored except `*.md` | Relaxed — no `docs` entry in `.gitignore`, nothing untracked |
| Document-numbering race (JV/SI/AP/CD/CR) | Fixed via `app/utils/concurrency.py` (`flush_or_suggest_fresh_number`, `commit_with_renumber_retry`); TDD-backed. See `docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md` |

---

## Open tech debt

**Duplicated designer JS (~3,600 lines).** Eight `app/static/js/*_preprinted_designer.js` files at
431–471 lines each — `apv` and `cdv` differ by exactly **two lines** (a comment and a `fetch()`
URL). The Python side already shares `app/common/preprinted_base.py`; the JS side never got the same
treatment. Highest-leverage cleanup available.

**Residual hardcoded GL codes in the WHT path.** `app/withholding_tax/models.py:38-39` — a NULL
`payable_account_id` / `receivable_account_id` silently falls back to hardcoded `20301` / `10212`
in the posting views, bypassing the otherwise fail-closed `control_accounts` design.

**`log_audit()` self-commits and swallows every exception** (`app/audit/utils.py:63`). Deliberate
availability trade-off — a failed audit write never fails the business operation — but an audit row
can be lost silently, and the self-commit can interleave with a caller's open transaction. Worth
revisiting for a system whose selling point is the BIR audit trail.

**Rate limiting is `memory://`** (`config.py`), therefore per-worker on PythonAnywhere: the
effective limit is looser than configured and resets on reload. Point `RATELIMIT_STORAGE_URI` at
Redis when one is available.

**Fat view modules** — `reports/views.py` 2,655 lines · `accounts_payable/views.py` 1,922 ·
`cash_disbursements/views.py` 1,626 · `sales_invoices/views.py` 1,594 · `cash_receipts/views.py`
1,454 · `payroll/views.py` 1,342.

**No regression gate.** Nothing currently maps a changed high-blast-radius shared file to the
modules that depend on it, and there is no pre-push hook. The Playwright e2e specs remain under
`tests/e2e/` (20 files) and still run with `pytest -m e2e`, but they are opt-in and nothing
enforces them.

**Undocumented conventions cited by dangling comments.** Comments in `app/payroll/models.py:196`,
`app/reports/books_data.py:60` and ~24 other files point at a conventions document that is no
longer in the repo, leaving the rules themselves unwritten — notably *never use a naive
`datetime.now()`* (use `ph_now()`, Philippine time) and *a SQLite batch `add_column` cannot carry
an inline FK*. Fold those rules into this document or into the relevant module docstrings and
drop the dangling pointers. `.gitignore:63-70` similarly describes tooling directories that are
no longer part of the project.
