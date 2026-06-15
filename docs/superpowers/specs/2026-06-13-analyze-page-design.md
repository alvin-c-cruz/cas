# /analyze-page Skill Design

**Date:** 2026-06-13
**Status:** Approved — ready for implementation

---

## Overview

A personal Claude Code skill invoked as `/analyze-page <url>` that performs a
comprehensive single-page analysis of a running CAS Flask application. It
combines a live browser pass (via Playwright MCP) with a source trace (reading
the Flask view, template, and models) to produce a single, actionable terminal
report across seven dimensions.

The skill is **self-enhancing**: every run ends with a "Skill Improvement Notes"
section that surfaces patterns worth adding to the skill's own checklist on the
next update.

---

## Section 1 — Invocation and Source Discovery

**Trigger:** `/analyze-page <url>`

**Pre-flight check (in this order):**

1. Confirm Flask dev server is running on port 5000 (or custom host if the URL
   is remote). If not reachable, stop and tell the user.
2. Load the page in Playwright (`mcp__playwright__browser_navigate`).
3. Take a snapshot (`mcp__playwright__browser_snapshot`) to capture the live DOM
   and visible state.
4. Take a screenshot (`mcp__playwright__browser_take_screenshot`) for visual
   reference.
5. Read the current URL from the snapshot to get the resolved path (handles
   redirects).

**Endpoint-to-source mapping** (derived from resolved URL path):

- Match the URL path against Flask's `url_map` mentally or by grepping
  `app/<feature>/views.py` files for `@<bp>.route('<path>')` patterns.
- Identify: the **view function**, its **blueprint**, and the **template(s)** it
  renders (look for `render_template(...)` calls).
- Read all identified source files before starting any dimension analysis.

**Files to read (minimum):**

| File type | Where to find it |
|-----------|-----------------|
| View function | `app/<feature>/views.py` |
| Template(s) | `app/<feature>/templates/...` |
| Model(s) | `app/<feature>/models.py` (if queried in the view) |
| Forms | `app/<feature>/forms.py` (if the page has a form) |

If the page calls helper utilities (e.g., `app/utils/`, `app/audit/utils.py`),
read those too.

---

## Section 2 — Browser Pass (UI + UX)

Performed entirely from the Playwright snapshot and screenshot. No source
reading in this pass.

**UI checks:**

- Layout integrity: missing elements, broken grid, truncated text, overlapping
  elements
- Responsive layout: resize to 768px (`mcp__playwright__browser_resize`) and
  check for overflow, hidden controls, broken tables
- Badge/status display: are counts, labels, and status chips visible and
  correct?
- Form field rendering: labels present, required markers, placeholder text
- Button labels: verify "Enter" for transactions, "Create" for master data
  (per project convention)
- Table column alignment and header clarity

**UX checks:**

- Confusing or ambiguous flows: is the next action obvious?
- Missing success/error feedback: flash messages or inline validation present?
- Dead links or broken navigation
- Multi-step tasks that could be single-step (efficiency note)
- Auto-population opportunities (e.g., today's date, default branch)
- Void vs. cancel distinction clarity (where applicable)

Each finding is tagged `[UI]` or `[UX]` with a severity level.

---

## Section 3 — Source Trace

Four sub-dimensions, each reading the source files identified in Section 1.

### 3a — Security

- **Authentication gate:** Does the view have `@login_required` (or equivalent
  redirect) on every route?
- **Role enforcement:** Are role checks present for write operations
  (`if current_user.role not in [...]`)? Are they consistent with the template
  role gates?
- **CSRF:** Does every `<form>` in the template include `{{ csrf_token() }}`?
  Does the view use `@csrf.exempt` without justification?
- **Input validation:** Is user-supplied input validated via WTForms or explicit
  checks before it hits the DB?
- **Sensitive data exposure:** Does the template or API response expose fields
  (e.g., password hashes, tokens) that should be hidden?
- **Direct object access:** Does the view verify the requested record belongs to
  the current user/branch?

### 3b — Queries

- **N+1 patterns:** Does the view call a query inside a loop (e.g., a `.first()`
  or `.count()` per list row)?
- **Missing `.filter_by()`:** Are list queries unintentionally unfiltered (no
  branch scope, no status filter)?
- **Eager loading:** Are relationships accessed that trigger lazy loads in a
  loop? Could `.options(joinedload(...))` help?
- **Unbounded queries:** Is there a `.all()` with no `.limit()` on a
  potentially large table?
- **Redundant queries:** Same query called twice in the same request (could be
  cached or reused)?

### 3c — Data Integrity

- **Audit logging:** Does every create/update/delete call `log_audit(...)` (or
  a shortcut like `log_create`)? Are `old_values` and `new_values` captured
  correctly?
- **Transaction scope:** Are related writes wrapped in a single
  `db.session.commit()`? Is there a bare `db.session.add()` without a following
  `commit()`?
- **Approval workflow:** If the entity is approval-gated (accounts, VAT, WHT),
  does the view go through the `*ChangeRequest` model?
- **Cascade/orphan safety:** On delete, are child records handled (cascaded,
  blocked, or explicitly cleaned up)?
- **Philippine Standard Time:** Are all `datetime` fields set via `ph_now()` or
  `ph_datetime()`? Any bare `datetime.now()` or `datetime.utcnow()`?

### 3d — Code Quality (PEP 8 + Maintainability)

- **PEP 8:** Line length (≤ 79 chars where practical), naming conventions
  (snake_case for variables/functions, PascalCase for classes), spacing around
  operators and after commas, blank lines between top-level definitions.
- **Complexity:** Functions longer than ~40 lines or with deeply nested
  conditionals (3+ levels) are flagged.
- **Dead code:** Commented-out blocks, unused imports, unreachable branches.
- **Magic literals:** Hardcoded strings or numbers that should be constants or
  config values.
- **Docstrings/comments:** Missing function docstrings for public view functions;
  comments that describe *what* (redundant) rather than *why* (useful).
- **Reuse:** Logic duplicated across views that should be a shared utility.
- **Template complexity:** Jinja2 templates with heavy business logic that
  belongs in the view or model.

---

## Section 4 — Impact Analysis

After completing Sections 2 and 3, assess downstream effects of any finding
that touches shared code.

For each finding that modifies a **view function**, **model method**, **utility
function**, or **base template**:

1. **Who else calls this?** Grep for callers across the blueprint and
   cross-blueprint (e.g., `log_audit`, `ph_now`, shared Jinja macros).
2. **Dependent reports or exports:** Does a change to a model field affect
   `export_to_excel` / `export_to_csv` or any report query?
3. **Audit trail consistency:** If a field is added/removed, does the audit
   `old_values`/`new_values` snapshot need updating?
4. **Approval workflow ripple:** If an approval-gated entity's change_data
   schema is altered, do existing pending `*ChangeRequest` rows become
   inconsistent?
5. **Test coverage gap:** Is the affected function covered by an existing test?
   If not, note it as a gap.

Impact findings are not separate findings — they are appended to the original
finding as an "Impact:" sub-item.

---

## Section 5 — Report Format

The report is printed to the terminal only (no file output unless the user
requests it). Structure:

```
════════════════════════════════════════════════════
PAGE ANALYSIS REPORT
URL:      <url>
Page:     <title> (<endpoint function name>)
Files:    <list of source files read>
────────────────────────────────────────────────────

[1] UI
  FINDING-001 [HIGH]   Mobile layout breaks at 768px — table overflows viewport
    File: app/purchase_bills/templates/.../list.html:42
    Fix:  Wrap <table> in <div class="table-wrap"> (overflow-x: auto)

[2] UX
  FINDING-002 [MEDIUM] No success flash after vendor save
    File: app/vendors/views.py:87
    Fix:  Add flash("Vendor saved.", "success") before redirect

[3] SECURITY
  ...

[4] QUERIES
  ...

[5] DATA INTEGRITY
  ...

[6] CODE QUALITY
  ...

[7] IMPACT
  (impact items appended to their parent findings above; this section
   lists findings whose impact extends to other pages/modules)
  FINDING-007 [HIGH]   ph_now() missing in journal_entry save
    Impact: affects JournalEntry, PurchaseBill, Receipt — all use same
            pattern; same fix needed in 3 other views

────────────────────────────────────────────────────
PRIORITIZED ACTION PLAN
  1. [CRITICAL] ...  → fix in: app/...
  2. [HIGH]     ...  → fix in: app/...
  3. [HIGH]     ...  → fix in: app/...
  4. [MEDIUM]   ...  → fix in: app/...
  5. [MEDIUM]   ...  → fix in: app/...

SUMMARY
  Critical: N  |  High: N  |  Medium: N  |  Low: N
  Total findings: N

SKILL IMPROVEMENT NOTES
  Patterns or checks found this run not currently in the skill checklist:
  - <observation>
  (none if nothing new surfaced)
════════════════════════════════════════════════════
```

**Severity levels:**

| Level | Meaning |
|-------|---------|
| CRITICAL | Data loss, security breach, or broken core workflow |
| HIGH | Wrong behavior, missing data, or significant UX failure |
| MEDIUM | Sub-optimal but functional; noticeable friction |
| LOW | Style, minor inconsistency, future-proofing |

**Proposed Fix block** (attached to every finding):

- `File:` — path + line number (or range)
- `Fix:` — one sentence or short before/after snippet showing the change

The Prioritized Action Plan lists the top 5 findings by impact (CRITICAL first,
then HIGH). If there are fewer than 5 findings total, list all of them.

---

## Approach

**Browser-first (Approach A):** Playwright loads the page live, captures the
current DOM and visual state, then source files are read to trace the backend.
This ensures the analysis reflects the actual running state of the app (not just
what the code says), and catches runtime rendering issues that a pure code read
would miss.

---

## Skill File Location

`~/.claude/skills/analyze-page.md`

The skill is personal (not tracked by the CAS repo), consistent with `/launch`,
`/kill`, and `/run-tests`.
