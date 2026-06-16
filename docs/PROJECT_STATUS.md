# CAS — Project Status

_Last updated: 2026-06-17 · Active branch: `feature/add-vendor-inline-modal` (not yet merged to `main`)_

CAS (Computerized Accounting System) — an accounting-first ERP for Philippine SMEs, BIR-compliant.
Flask + SQLAlchemy + SQLite, app-factory + blueprints, double-entry core, multi-branch, role-based
access, approval workflow, full audit trail. See `CLAUDE.md` for architecture and conventions.

---

## Module status

| Area | Module | Status |
|---|---|---|
| Transactions | Accounts Payable (Enter Bill) | ✅ Live — primary, e2e-smoke covered |
| Transactions | Cash Disbursements (Pay Bill) | ✅ Live |
| Transactions | Journal Voucher | ✅ Live |
| Transactions | Sales Invoices (Bill Client) | 🟡 Live but **separate dev track**; has open bugs (BUG-02, BUG-15) |
| Transactions | Cash Receipts (Collection) | 🟡 Recently activated (Soon badge removed) — verify completeness |
| Ledger | Chart of Accounts | ✅ Live |
| Ledger | Aging of AP | ✅ Live |
| Ledger | General Ledger, Aging of AR | ⏳ Coming soon |
| Reports | Income Statement, Balance Sheet, Cash Flow, Trial Balance | ⏳ Coming soon |
| BIR | VAT Reports, Withholding Tax, Annual ITR | ⏳ Coming soon |
| Maintenance | Customers, Vendors, VAT Categories, Withholding Tax, Audit Log | ✅ Live |
| Admin | Company Settings, Branch Management, User Management, Approved Emails | ✅ Live |

---

## Recently completed (this branch, 2026-06-17)

- **Inline "➕ Add Vendor"** modal on AP + CD pickers; shared `initSearchSelect` typeahead
  (`app/static/search-select.js`); JSON-aware `/vendors/create`.
- **AP JE-preview fix** — Account Title shows the account name, not the line description (`d2f79f7`).
- **Nav polish** — "Save Vendor" button (`18b5040`); two-line transaction sidebar items with action
  verbs (`39ac276`/`14ef13d`); Cash Receipts activated (`2992ba6`).
- **Quality tooling** (see below): retro-agent, regression guard, search-select docs + skill.

---

## Quality tooling (new, 2026-06-17)

- **`/retro`** — post-work retrospective agent: reviews branch/session/backlog/tests, curates the
  persistent memory store, proposes (never auto-applies) code/rule changes. Found BUG-15 on its
  first run. (`.claude/agents/retro.md`)
- **`/guard`** + **pre-push hook** — maps changed high-blast-radius shared files →
  dependent modules (`.claude/regression-map.json`) and runs the affected **Playwright e2e smoke**;
  blocks a push on regression. Verified: a reintroduced BUG-15 made the gate fail and block.
- **e2e smoke** — `tests/e2e/test_ap_smoke.py` (AP create: line-items unlock, JE-preview account
  name, inline quick-add). Opt-in (`pytest -m e2e`); excluded from the default run.
- **Search-select** — feature reference (`docs/frontend/search-select.md`) + `/search-select`
  implementation skill.

Detail in memory: `project-regression-guard`, `project-search-select`.

---

## Open priorities

### 🔴 High — correctness & security (dedicated fix branches)
- **Security hardening (BUG-SEC-01/02/03):** no login rate-limit/lockout throttling; failed login
  returns 200 not 401; CSRF cookie not HttpOnly.
- **BUG-02:** VAT/WHT dropdowns empty in Sales Invoice line items (core blocker for posting SI).
- **BUG-10:** seeded COA missing AR / Revenue / Cash-in-Bank accounts (SI warns "AR 10201 not found").
- **BUG-13:** AP Voucher Description field not visible in line items (layout). _(Re-verify — much AP
  line-item work has landed since; may be stale.)_

### 🟠 Tier 1 — triage: stale test vs real product bug
- **VAT input-account workflow ×4** (`test_vat_input_account_workflow.py`) — drives purchase-JE
  input-VAT mapping correctness; highest stakes.
- **Change-request approval workflow ×3** (`test_change_request_workflow.py`) — approve/reject
  control for sensitive master data.
- **BUG-15** — Sales Invoice JE preview shows description in Account Title (`sales_invoices/form.html:570`);
  one-line fix, deferred to the **separate SI track**.

### 🟡 Tier 2-4 — vendor test gaps, reliability, housekeeping
- Vendor automation gaps (defaults endpoint, validation, WHT m2m, audit depth, exports).
- `search-select.js` name-collision risk (`customers/form.html:367` has a 4-arg `initSearchSelect`).
- BUG-V-04 (audit old/new diff), BUG-V-02 (delete-modal hardcoded colors), BUG-08 (AP vendor-select
  spinner). Housekeeping: relax `/docs/` ignore, remove stray root junk file.

Full lists: memory `project-bug-tracker`, `project-open-backlog`.

---

## Test health

- **Baseline (on `main`, 2026-06-15):** 12 failed + 1 error are **pre-existing** (reproduce on a
  clean baseline checkout — don't attribute to feature work). Groups: VAT input-account ×4,
  change-request ×3, branch-assignment ×1, under-development copy ×1, AP-form Playwright ×3,
  WHT isolation error ×1. See `project-preexisting-test-failures`.
- **New e2e smoke:** 3/3 green; gated out of the default suite.
- Run: `pytest` (default, excludes e2e) · `pytest -m e2e` (needs `python -m playwright install chromium`).

---

## Known tech debt / follow-ups
- Route the line-item **VT/WT code-only** selects through `initSearchSelect` (today they call
  `new Choices` directly, missing the shared typeahead).
- Mirror the AP e2e smoke to **CD** and **SI**; set their `e2e` path in `regression-map.json`.
- Resolve the `initSearchSelect` name collision (rename or migrate `customers/form.html`).
- Global error handlers are **disabled** in `create_app` (re-enable before production — see CLAUDE.md).
- `/docs/` is gitignored except `*.md`; some test-plan docs are untracked.
