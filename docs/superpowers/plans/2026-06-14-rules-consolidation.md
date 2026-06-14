# Rules Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate behavioral rules into CLAUDE.md, clean up redundant/stale memory files, and add per-module pytest markers to all test files.

**Architecture:** Four streams execute sequentially. Stream 1 edits CLAUDE.md and .gitignore. Stream 2 edits memory files. Stream 3 adds module markers to pytest.ini. Stream 4 tags every test file with `pytestmark`.

**Tech Stack:** Plain file edits (no Flask code changes). pytest --strict-markers enforced so all new markers must be declared in pytest.ini before tagging tests.

---

### Task 1: CLAUDE.md — Add Workflow Preferences + Session Start Protocol

**Files:**
- Modify: `CLAUDE.md` (root, 78 lines)

- [ ] **Step 1: Open CLAUDE.md and append two new sections after the last `## Gotchas` section**

The file currently ends at line 78. Append this verbatim after the last line:

```markdown

## Workflow Preferences

These override default skill behavior:

- **Auto-invoke subagent-driven development.** After `writing-plans` completes, invoke
  `superpowers:subagent-driven-development` immediately — do NOT present a "which approach?"
  choice first.
- **Skip finishing-branch options menu.** After all tasks are committed and pushed and tests
  pass, summarize what was done in 2-3 sentences. Do not invoke `finishing-a-development-branch`
  or present the 4-option menu.
- **Testing scope tie-breaker.** If a bug is found during testing:
  - In a module you are **currently touching** → fix inline and continue.
  - In a module you are **not touching at all** → stop, scope it separately, then continue.

## Session Start Protocol

At the start of every new conversation, before responding to the first user message:
1. Read `MEMORY.md` (already in context via system-reminder)
2. Output exactly: `Session start — [N] memory rules loaded · CLAUDE.md reviewed · Ready.`
   where N = number of entries listed in MEMORY.md
3. Then proceed with the task
```

- [ ] **Step 2: Verify CLAUDE.md content**

Read the file and confirm both new sections appear after `## Gotchas`.

- [ ] **Step 3: Commit**

```powershell
git add -f CLAUDE.md
git commit -m "docs: add Workflow Preferences and Session Start Protocol to CLAUDE.md"
```

---

### Task 2: .gitignore — Whitelist CLAUDE.md and PROJECT_FOUNDATIONS.md

**Files:**
- Modify: `.gitignore` (root)

- [ ] **Step 1: Find the README.md whitelist line in .gitignore**

Search for `!README.md` in `.gitignore`.

- [ ] **Step 2: Add two more whitelist lines immediately after `!README.md`**

```
!CLAUDE.md
!PROJECT_FOUNDATIONS.md
```

- [ ] **Step 3: Also update the TODO comment in app/__init__.py**

At line 383 of `app/__init__.py`, the current comment is:
```python
    # TODO: Re-enable after testing complete
```

Replace it with:
```python
    # TODO: re-enable error handlers before production deployment
```

- [ ] **Step 4: Commit**

```powershell
git add .gitignore app/__init__.py
git commit -m "chore: whitelist CLAUDE.md + PROJECT_FOUNDATIONS.md in .gitignore; clarify error handler TODO"
```

---

### Task 3: Memory Consolidation

**Files (all in `C:\Users\user\.claude\projects\C--envs-cas\memory\`):**
- Delete: `feedback-execution-approach.md`
- Delete: `feedback-finishing-branch.md`
- Slim: `cas-dev-rules.md`
- Rename+strip: `branch-architecture-gaps.md` → `branch-scoping-rule.md`
- Split+delete: `cas-test-run-progress.md` → new `apv-playwright-quirks.md`
- Update: `document-numbering-system.md`
- Modify: `MEMORY.md` (index)

**Note:** Memory files live outside the git repo. No commit needed — edits are immediate.

- [ ] **Step 1: Delete feedback-execution-approach.md**

Delete `C:\Users\user\.claude\projects\C--envs-cas\memory\feedback-execution-approach.md`.

- [ ] **Step 2: Delete feedback-finishing-branch.md**

Delete `C:\Users\user\.claude\projects\C--envs-cas\memory\feedback-finishing-branch.md`.

- [ ] **Step 3: Slim cas-dev-rules.md**

Read the current file, then overwrite it keeping ONLY the rules that are NOT already in CLAUDE.md. Based on current content, keep only:

```markdown
---
name: cas-dev-rules
description: CAS dev workflow gates not covered by CLAUDE.md — Playwright/server coupling, seeds/fixtures sync
metadata:
  type: feedback
---

Kill the dev server before running Playwright tests (port 5000 conflict).

**Why:** The Playwright smoke suite starts its own Flask server. If the dev server is already running on port 5000, tests fail with address-in-use errors.

**How to apply:** Before `pytest tests/smoke/` or any Playwright run, stop the Flask dev server first.

---

Seeds and test fixtures must stay in sync. When the seed data adds a new field or changes a default, update `tests/conftest.py` user/branch/settings fixtures to match.

**Why:** Tests that rely on seeded data break silently when seeds drift from fixture assumptions.

**How to apply:** Any time `app/seeds/` changes, grep conftest.py for related fixture setup and update it.
```

- [ ] **Step 4: Create branch-scoping-rule.md (rename + strip branch-architecture-gaps.md)**

Create new file `C:\Users\user\.claude\projects\C--envs-cas\memory\branch-scoping-rule.md`:

```markdown
---
name: branch-scoping-rule
description: All new transactional features must be branch-scoped from day one
metadata:
  type: feedback
---

All new transactional features must be branch-scoped from day one. Query by `session['selected_branch_id']`.

**Why:** SalesInvoice, PurchaseBill, and Receipt were built without branch_id and required a retroactive migration — expensive and risky.

**How to apply:** When adding any new model that represents a transaction or document, include `branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)` from the start. Do not defer it.
```

Then delete the old file `branch-architecture-gaps.md`.

- [ ] **Step 5: Create apv-playwright-quirks.md (extracted from cas-test-run-progress.md)**

Create `C:\Users\user\.claude\projects\C--envs-cas\memory\apv-playwright-quirks.md`:

```markdown
---
name: apv-playwright-quirks
description: Browser automation quirks for APV (AP Voucher) Playwright smoke tests
metadata:
  type: feedback
---

The login password field is `readonly` (anti-autofill). In Playwright, call `click('#password')` first to clear it before `fill()` or `type()`.

**Why:** The field is programmatically set to readonly to prevent browser autofill. Clicking it triggers a JS handler that removes the readonly attribute.

**How to apply:** In any Playwright test that logs in, use:
```python
page.click('#password')
page.fill('#password', password)
```
not just `page.fill('#password', password)` directly.

APV form: the Vendor field uses Choices.js. Use `page.click('.choices')` then `page.fill('.choices__input', vendor_name)` and wait for the dropdown option before clicking it.
```

Then delete `cas-test-run-progress.md`.

- [ ] **Step 6: Update document-numbering-system.md**

Overwrite with corrected formats:

```markdown
---
name: document-numbering-system
description: Document number formats used in CAS — use these when generating or validating record numbers
metadata:
  type: project
---

Document number formats in CAS:

| Document | Format | Sequence |
|---|---|---|
| AP Voucher | `AP-YYYY-MM-NNNN` | Monthly reset |
| Journal Voucher | `JV-YYYY-MM-NNNN` | Monthly reset |
| Sales Invoice | `SI-YYYY-NNNN` | Annual (no month) |
| Journal Entry | `JE-YYYY-NNNN` | Annual (no month) |
| Cash Receipt | `CR-YYYY-NNNN` | Annual (no month) |
| Cash Payment | `CP-YYYY-NNNN` | Annual (no month) |

**How to apply:** Use these formats when generating next-sequence numbers or writing assertions in tests. AP and JV reset to 0001 each month; SI, JE, CR, CP reset to 0001 each year.
```

- [ ] **Step 7: Update MEMORY.md index**

Read the current `MEMORY.md` then rewrite it removing entries for deleted files (`feedback-execution-approach`, `feedback-finishing-branch`, `cas-test-run-progress`, `branch-architecture-gaps`) and adding/updating:
- Add: `- [APV Playwright quirks](apv-playwright-quirks.md) — password field readonly workaround; Choices.js vendor picker pattern`
- Update `branch-architecture-gaps` entry → `- [Branch scoping rule](branch-scoping-rule.md) — all new transactional models must include branch_id from day one`
- Remove `Execution approach` and `No finishing-branch prompt` entries (now in CLAUDE.md)

---

### Task 4: pytest.ini — Add Module Markers

**Files:**
- Modify: `pytest.ini`

- [ ] **Step 1: Add module markers to the markers section**

After the existing `performance: ...` line (line 36), add:

```ini
    # Module markers — run a single module: pytest -m purchase_bills
    purchase_bills: Purchase bills / AP vouchers module
    sales_invoices: Sales invoices module
    receipts: Cash receipts and payments module
    journal_entries: Journal entries module
    journals: Journal views (AP journal, voucher journal)
    accounts: Chart of accounts module
    vendors: Vendors module
    customers: Customers module
    reports: Financial and BIR reports
    branches: Branch management
    users: User management and auth
    audit: Audit trail
    periods: Accounting periods
    vat_categories: VAT categories
    withholding_tax: Withholding tax codes
    settings: App settings / company settings
```

- [ ] **Step 2: Verify pytest still starts**

```powershell
pytest --collect-only -q 2>&1 | head -5
```

Expected: no "PytestUnknownMarkWarning" or marker errors. If markers error, the section indentation is wrong — all marker lines need 4 spaces of indent.

- [ ] **Step 3: Commit**

```powershell
git add pytest.ini
git commit -m "test: add per-module pytest markers to pytest.ini"
```

---

### Task 5: Tag All Test Files with Module pytestmark

**Files:** All 40+ test files listed below. Each gets `pytestmark` added at the top, after existing imports.

**Rule:** `pytestmark` must be a module-level list, e.g. `pytestmark = [pytest.mark.journals, pytest.mark.integration]`. Files that already have a layer marker in their `pytestmark` keep it; the module marker is additive.

**Mapping (file → module markers to add):**

| File | Module marker(s) |
|---|---|
| `tests/unit/test_ap_journal_data.py` | `journals` |
| `tests/integration/test_ap_journal_columnar.py` | `journals` |
| `tests/integration/test_journals.py` | `journals` |
| `tests/unit/test_journal_utils.py` | `journal_entries` |
| `tests/unit/test_purchase_bill_models.py` | `purchase_bills` |
| `tests/unit/test_purchase_bill_notes_required.py` | `purchase_bills` |
| `tests/unit/test_purchase_bills_utils.py` | `purchase_bills` |
| `tests/unit/test_record_status.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_views.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_detail.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_void.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_dates.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_je.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_je_lifecycle.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_vat_buckets.py` | `purchase_bills` |
| `tests/integration/test_purchase_bill_override.py` | `purchase_bills` |
| `tests/smoke/test_purchase_bill_form.py` | `purchase_bills` |
| `tests/integration/test_sales_invoice_views.py` | `sales_invoices` |
| `tests/integration/test_receipt_views.py` | `receipts` |
| `tests/integration/test_branch_assignment.py` | `branches` |
| `tests/integration/test_branch_session_validation.py` | `branches` |
| `tests/unit/test_branch_utils.py` | `branches` |
| `tests/integration/test_auth.py` | `users` |
| `tests/integration/test_auth_audit.py` | `users`, `audit` |
| `tests/unit/test_user_model.py` | `users` |
| `tests/integration/test_sidebar_roles.py` | `users` |
| `tests/integration/test_dashboard_roles.py` | `users` |
| `tests/integration/test_approved_emails.py` | `users` |
| `tests/integration/test_viewer_readonly_ui.py` | `users` |
| `tests/unit/test_vendor_model.py` | `vendors` |
| `tests/integration/test_vendor_views.py` | `vendors` |
| `tests/unit/test_vat_category_model.py` | `vat_categories` |
| `tests/unit/test_vat_category_form.py` | `vat_categories` |
| `tests/integration/test_vat_input_account_workflow.py` | `vat_categories` |
| `tests/integration/test_change_request_workflow.py` | `accounts` |
| `tests/integration/test_account_request_history.py` | `accounts` |
| `tests/integration/test_sole_accountant_autoapprove.py` | `accounts` |
| `tests/unit/test_wht_per_line_item.py` | `withholding_tax` |
| `tests/integration/test_company_settings_views.py` | `settings` |
| `tests/integration/test_under_development.py` | *(no module marker — general)* |
| `tests/test_smoke.py` | *(already has `smoke` layer marker — no module marker needed)* |
| `tests/performance/test_database_performance.py` | *(already has `performance` layer marker — no module marker needed)* |

- [ ] **Step 1: For each file in the mapping, read the file and add `pytestmark`**

**Pattern for files that have NO existing `pytestmark`:** Add after the last import line:

```python
import pytest
pytestmark = [pytest.mark.<module>, pytest.mark.<layer>]
```

Where `<layer>` is `unit` or `integration` based on the directory. For smoke files use `smoke`.

**Pattern for files that ALREADY have `pytestmark`:** Append the module marker to the existing list.

Example — `tests/unit/test_ap_journal_data.py` currently has no pytestmark. Add:
```python
import pytest
pytestmark = [pytest.mark.journals, pytest.mark.unit]
```

Example — `tests/integration/test_auth_audit.py` gets two module markers:
```python
pytestmark = [pytest.mark.users, pytest.mark.audit, pytest.mark.integration]
```

- [ ] **Step 2: Run the full suite to confirm no marker warnings**

```powershell
pytest --collect-only -q 2>&1 | grep -i "warning\|error" | head -20
```

Expected: zero marker-related warnings.

- [ ] **Step 3: Run a module-scoped subset to prove the feature works**

```powershell
pytest -m purchase_bills -q
```

Expected: only purchase_bills tests collected and run (no journals, no vendor, etc.).

```powershell
pytest -m "journals and unit" -q
```

Expected: only `test_ap_journal_data.py` tests run.

- [ ] **Step 4: Run the full test suite**

```powershell
pytest -q
```

Expected: same pass/fail count as before this task (no regressions from pytestmark additions).

- [ ] **Step 5: Commit**

```powershell
git add tests/
git commit -m "test: add per-module pytestmark to all test files"
```

---

## Usage After Implementation

```powershell
# Run all purchase bill tests (unit + integration)
pytest -m purchase_bills

# Run only journal unit tests
pytest -m "journals and unit"

# Run all tests for a specific module in verbose mode
pytest -m vendors -v

# Existing layer-only usage unchanged
pytest -m unit
pytest -m "not slow"
pytest  # full suite
```
