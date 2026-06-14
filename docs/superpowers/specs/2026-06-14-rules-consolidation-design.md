# Rules Consolidation & Per-Module Testing Design Spec

**Date:** 2026-06-14

## Problem

Three categories of issues identified in a rules/skills audit:

1. **Memory rules not reliably overriding skill behavior** — behavioral preferences (auto-subagent, no finishing-branch menu) live in memory files but skills still present the prompts, so preferences get ignored.
2. **Memory duplication** — `cas-dev-rules` repeats much of CLAUDE.md; stale memories (branch gaps resolved, ephemeral test state) add noise.
3. **No per-module test isolation** — tests can only be run by layer (unit/integration) or all at once; no way to run all tests for a single module.

## Design Decisions

- **CLAUDE.md is the source of truth for behavioral rules.** It has the highest priority and reliably overrides skill prompts. Workflow preferences move there.
- **Memory files are for project-specific, non-obvious, non-CLAUDE.md facts.** Rules that duplicate CLAUDE.md are deleted from memory.
- **Skills are trusted as-is.** No skill files are modified. CLAUDE.md additions make preferences stick.
- **pytest markers for module isolation.** Existing layer markers (unit, integration) are kept alongside new module markers. Both can be combined: `pytest -m "purchase_bills and integration"`.

---

## Stream 1: CLAUDE.md + .gitignore Fixes

### 1a. Add Workflow Preferences section to CLAUDE.md

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
```

### 1b. Fix .gitignore to track CLAUDE.md and PROJECT_FOUNDATIONS.md

Add to `.gitignore` (alongside the existing `README.md` whitelist):
```
!CLAUDE.md
!PROJECT_FOUNDATIONS.md
```

### 1c. Add production TODO in create_app

In `app/__init__.py`, next to the disabled global error handlers comment, add:
```python
# TODO: re-enable error handlers before production deployment
```

---

## Stream 2: Memory Consolidation

### Delete (encoded in CLAUDE.md or no longer needed)
- `feedback-execution-approach.md` — now in CLAUDE.md Workflow Preferences
- `feedback-finishing-branch.md` — now in CLAUDE.md Workflow Preferences

### Slim (remove content that duplicates CLAUDE.md, keep unique content only)
- `cas-dev-rules.md` — keep only: Playwright/server coupling rule, kill-before-start rule, seeds/fixtures sync rule. Remove: brainstorm-before-implementing, ripple effects, no hardcoded styling, responsive, audit trail in tests, multi-branch rule (all in CLAUDE.md).

### Rename + strip (stale content)
- `branch-architecture-gaps.md` → `branch-scoping-rule.md` — remove resolved items list. Keep only: "All new transactional features must be branch-scoped from day one. Query by `session['selected_branch_id']`."

### Split (separate ephemeral from reusable)
- `cas-test-run-progress.md` — remove: commit SHAs, bug IDs, DB snapshot (all ephemeral). Extract APV browser automation quirks into a new `apv-playwright-quirks.md` memory. Delete the original.

### Update (correct inaccurate content)
- `document-numbering-system.md` — update to reflect actual formats in use:
  - `AP-YYYY-MM-NNNN` (monthly reset) — AP vouchers
  - `JV-YYYY-MM-NNNN` (monthly reset) — journal vouchers
  - `SI-YYYY-NNNN` (annual sequence, no month) — sales invoices
  - `JE-YYYY-NNNN` (annual sequence, no month) — journal entries
  - `CR-YYYY-NNNN` / `CP-YYYY-NNNN` — receipts/payments

### Update MEMORY.md index
Remove entries for deleted files. Add entry for new `apv-playwright-quirks.md`. Update `branch-architecture-gaps` → `branch-scoping-rule`.

---

## Stream 3: Per-Module Pytest Markers

### pytest.ini additions

Add to the `markers =` section in `pytest.ini`:

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

### Tagging existing tests

Each test file gets one or more module markers via `pytestmark` at the top of the file:

```python
# tests/integration/test_ap_journal_columnar.py
import pytest
pytestmark = [pytest.mark.journals, pytest.mark.integration]
```

```python
# tests/unit/test_ap_journal_data.py
import pytest
pytestmark = [pytest.mark.journals, pytest.mark.unit]
```

All existing tests keep their current layer markers (`unit`, `integration`, etc.). Module markers are additive.

### Usage after implementation
```bash
pytest -m purchase_bills          # all purchase bill tests
pytest -m "journals and unit"     # unit tests for journals only
pytest -m "not slow"              # unchanged existing behavior
pytest                            # full suite unchanged
```

---

## Out of Scope

- Modifying any skill files in the plugin cache
- Moving tests to a module-based folder structure (marker approach chosen instead)
- Fixing the pre-existing `test_branch_assignment` failure (separate issue)
