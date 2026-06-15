# /analyze-page Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a personal Claude Code skill at `~/.claude/skills/analyze-page.md` that performs a comprehensive 7-dimension analysis of any running CAS page via Playwright + source trace and prints a structured terminal report.

**Architecture:** Single markdown skill file. No Python code, no migrations, no tests in the pytest sense. Each section of the skill is a self-contained checklist; the "test" for each section is a manual spot-check against the spec. The final task is a live smoke run to verify the skill produces well-structured output.

**Tech Stack:** Claude Code skill (markdown), Playwright MCP, Flask/Jinja2 source reading.

**Spec:** `docs/superpowers/specs/2026-06-13-analyze-page-design.md` — read it before starting.

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `~/.claude/skills/analyze-page.md` | The skill file — all content lives here |

---

### Task 1: Scaffold + Frontmatter + Section Headers

**Files:**
- Create: `C:\Users\user\.claude\skills\analyze-page.md`

- [ ] **Step 1: Read the spec**

  Read `docs/superpowers/specs/2026-06-13-analyze-page-design.md` in full before writing a single line.

- [ ] **Step 2: Create the skill file with frontmatter and empty section headers**

  Write the following to `C:\Users\user\.claude\skills\analyze-page.md`:

  ```markdown
  ---
  name: analyze-page
  description: Use when the user types /analyze-page <url> to perform a comprehensive 7-dimension analysis (UI, UX, Security, Queries, Data Integrity, Code Quality, Impact) of a running CAS Flask page via Playwright and source trace. Produces a structured terminal report with proposed fixes and a prioritized action plan.
  ---

  # /analyze-page — Comprehensive Page Analysis

  Performs a live browser pass + source trace of a CAS Flask page across 7 dimensions.
  Produces a terminal report with proposed fixes and a Prioritized Action Plan.

  ---

  ## Step 0: Pre-flight

  ## Step 1: Source Discovery

  ## Step 2: Browser Pass — UI

  ## Step 3: Browser Pass — UX

  ## Step 4: Source Trace — Security

  ## Step 5: Source Trace — Queries

  ## Step 6: Source Trace — Data Integrity

  ## Step 7: Source Trace — Code Quality (PEP 8 + Maintainability)

  ## Step 8: Impact Analysis

  ## Step 9: Report

  ## Severity Reference
  ```

- [ ] **Step 3: Spot-check**

  Verify the file exists and has 9 numbered steps plus Severity Reference.
  Run: `Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Select-String "## Step"`
  Expected: 10 matching lines (Step 0–9).

- [ ] **Step 4: Commit**

  ```powershell
  git -C C:\envs\cas add --intent-to-add . 2>$null; Write-Host "scaffold noted"
  ```
  *(No git commit yet — skill file is outside the repo. Note: commits happen after each subsequent task.)*

---

### Task 2: Pre-flight and Source Discovery (Steps 0–1)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Steps 0 and 1

- [ ] **Step 1: Write Step 0 — Pre-flight**

  Replace the `## Step 0: Pre-flight` placeholder with:

  ```markdown
  ## Step 0: Pre-flight

  **Invocation:** `/analyze-page <url>`

  Before any analysis:

  1. Confirm the server is reachable. Try:
     ```
     mcp__playwright__browser_navigate  url=<url>
     ```
     If the page fails to load (connection refused, 500), stop and report the error verbatim. Do not proceed.

  2. Take a **snapshot** (captures live DOM + accessibility tree):
     ```
     mcp__playwright__browser_snapshot
     ```

  3. Take a **screenshot** (visual reference):
     ```
     mcp__playwright__browser_take_screenshot
     ```

  4. Read the resolved URL from the snapshot (it may differ from the input if there was a redirect).
     Record: `resolved_url`, `page_title`.
  ```

- [ ] **Step 2: Write Step 1 — Source Discovery**

  Replace the `## Step 1: Source Discovery` placeholder with:

  ```markdown
  ## Step 1: Source Discovery

  Map the resolved URL path to Flask source files **before** starting any dimension analysis.

  **How to find the view:**

  - The URL path pattern (e.g. `/purchase-bills`, `/vendors/3/edit`) maps to a blueprint route.
  - Grep for the route decorator across all view files:
    ```
    Grep pattern: route\(['"]<path-segment>
    glob: app/*/views.py
    ```
  - Identify: **view function name**, **blueprint name**, **template(s)** rendered
    (look for `render_template(...)` calls in the view body).

  **Minimum files to read:**

  | File type | Location |
  |-----------|----------|
  | View function | `app/<feature>/views.py` |
  | Template(s) | `app/<feature>/templates/...` |
  | Model(s) | `app/<feature>/models.py` (if queried) |
  | Form(s) | `app/<feature>/forms.py` (if page has a form) |

  Also read any helpers called by the view (e.g. `app/utils/`, `app/audit/utils.py`).

  **Record at the top of your working notes:**
  ```
  Endpoint:  <function_name>  (<blueprint_name>)
  Template:  <path>
  Model(s):  <list>
  Form(s):   <list>
  Helpers:   <list>
  ```

  Do NOT start dimension analysis until all source files are read.
  ```

- [ ] **Step 3: Spot-check**

  Verify Steps 0 and 1 each contain their full content.
  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 60 lines total.

---

### Task 3: Browser Pass — UI and UX (Steps 2–3)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Steps 2 and 3

- [ ] **Step 1: Write Step 2 — UI Checks**

  Replace `## Step 2: Browser Pass — UI` with:

  ```markdown
  ## Step 2: Browser Pass — UI

  Work entirely from the Playwright snapshot and screenshot (no source reading in this pass).

  Check each item. Any failure → create a finding tagged `[UI]`.

  - [ ] **Layout integrity:** Any missing elements, broken grid, truncated text, or overlapping elements?
  - [ ] **Responsive (768 px):** Resize the browser:
        ```
        mcp__playwright__browser_resize  width=768  height=900
        ```
        Then re-snapshot. Look for: table overflow, hidden controls, broken flex/grid, buttons that fall off-screen.
        Resize back to 1280×900 after.
  - [ ] **Badge/status display:** Are counts, labels, role badges, and status chips visible and correct?
  - [ ] **Form field rendering:** Labels present? Required markers (`*`)? Placeholder text where helpful?
  - [ ] **Button labels:**
        - Transaction documents (`purchase_bills`, `sales_invoices`, `receipts`, `journal_entries`): button must say **"Enter [Document]"**, NOT "Create"
        - Master data (`vendors`, `customers`, `accounts`, `branches`, `users`): button must say **"+Create"**
        If the wrong verb is used → HIGH finding.
  - [ ] **Table headers and column alignment:** Headers clear? Currency columns right-aligned? Date columns consistent width?
  - [ ] **Empty states:** If the list is empty, is there a helpful message (not a blank table)?
  ```

- [ ] **Step 2: Write Step 3 — UX Checks**

  Replace `## Step 3: Browser Pass — UX` with:

  ```markdown
  ## Step 3: Browser Pass — UX

  Still browser-only. Tag findings `[UX]`.

  - [ ] **Next action clarity:** Is the primary action for this page immediately obvious?
  - [ ] **Success/error feedback:** After a form submission, is there a flash message or inline validation?
        (If you cannot submit the form in this analysis pass, note it as "not tested — requires form data".)
  - [ ] **Dead links / 404 navigation:** Click every nav link visible on the page (sidebar, breadcrumb, action buttons).
        Any that 404 or land on an Under Development page unexpectedly → MEDIUM finding.
  - [ ] **Multi-step tasks:** Any action that requires 3+ steps that could reasonably be 1–2?
        Note as MEDIUM efficiency finding.
  - [ ] **Auto-population opportunities:** Could the form pre-fill today's date, the current branch, or the
        last-used vendor? Note as LOW if missing.
  - [ ] **Void vs. Cancel distinction** (AP Vouchers / Sales Invoices only): Is the difference between
        "Cancel" (soft delete, no reversal) and "Void" (accounting reversal entry) visually clear to the user?
  - [ ] **Confirmation modals:** Any destructive action (delete, void, cancel) that uses a JavaScript
        `confirm()` popup instead of a custom HTML modal → CRITICAL finding.
        Per project convention: **no JS popups, ever.** All confirmations must be HTML modals with `{{ csrf_token() }}`.
  ```

- [ ] **Step 3: Spot-check**

  Verify Steps 2 and 3 are populated.
  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 120 lines.

---

### Task 4: Source Trace — Security and Queries (Steps 4–5)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Steps 4 and 5

- [ ] **Step 1: Write Step 4 — Security**

  Replace `## Step 4: Source Trace — Security` with:

  ```markdown
  ## Step 4: Source Trace — Security

  Read the view function and template. Tag findings `[SECURITY]`.

  - [ ] **Authentication gate:** Does the view have `@login_required` on every route (GET and POST)?
        If any route lacks it → CRITICAL.
  - [ ] **Role enforcement (write operations):** For any POST/DELETE route, is there a role check?
        ```python
        # Expected pattern:
        if current_user.role not in ['accountant', 'admin']:
            flash('...', 'danger')
            return redirect(url_for(...))
        ```
        Missing role check on a write route → CRITICAL.
  - [ ] **Template role gates consistent with view:** If the view blocks a role, the template should also
        hide the write controls for that role. Mismatch → HIGH (confusing UX, potential info leak).
  - [ ] **CSRF tokens:** Every `<form>` in the template must contain `{{ csrf_token() }}` (or
        `{{ form.hidden_tag() }}` which includes it). Missing → CRITICAL.
  - [ ] **`@csrf.exempt` without justification:** If present, it must have a comment explaining why.
        Unjustified → HIGH.
  - [ ] **Input validation:** User-supplied query parameters or form fields used in a DB query must be
        validated (WTForms validators, explicit type casting, or `.filter_by()` with typed params).
        Raw `request.args.get(...)` fed directly into a query → HIGH.
  - [ ] **Sensitive data exposure:** Does the template render fields that should not be visible
        (password hashes, tokens, internal IDs used as surrogate keys in URLs without ownership check)?
        → CRITICAL if exposed.
  - [ ] **Direct object access:** For detail/edit views (`/resource/<id>`), does the view verify
        the record belongs to the current branch or user?
        ```python
        # Expected pattern:
        record = Model.query.get_or_404(id)
        if record.branch_id != session.get('selected_branch_id'):
            abort(403)
        ```
        Missing ownership check → HIGH.
  ```

- [ ] **Step 2: Write Step 5 — Queries**

  Replace `## Step 5: Source Trace — Queries` with:

  ```markdown
  ## Step 5: Source Trace — Queries

  Read the view function (and any model methods it calls). Tag findings `[QUERY]`.

  - [ ] **N+1 pattern:** Is there a SQLAlchemy query inside a Python loop?
        ```python
        # Bad:
        for bill in bills:
            vendor = Vendor.query.get(bill.vendor_id)   # ← N+1
        ```
        → HIGH. Propose `.options(joinedload(PurchaseBill.vendor))` or a joined query.
  - [ ] **Unfiltered list query:** Does a `.all()` query have no `.filter_by()` or `.filter()`?
        On a multi-tenant or multi-branch app this leaks data across branches → HIGH.
        Expected: every list query scoped to the current branch:
        ```python
        bills = PurchaseBill.query.filter_by(branch_id=session['selected_branch_id']).all()
        ```
  - [ ] **Unbounded query (no LIMIT):** A `.all()` on a table that could grow to thousands of rows
        with no pagination or `.limit()` → MEDIUM.
  - [ ] **Redundant queries:** Same query executed twice in the same request (e.g., count + list
        fetching the same rows). Could be combined or cached → MEDIUM.
  - [ ] **Eager loading opportunity:** Relationship attribute accessed in a loop (Jinja2 template
        `{% for item in bill.items %}`) with no `.options(...)` on the parent query → MEDIUM.
  - [ ] **`.get()` on deleted records:** `Model.query.get(id)` returns `None` for a soft-deleted record
        without checking `is_deleted` or status → LOW (depends on model design).
  ```

- [ ] **Step 3: Spot-check**

  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 210 lines.

---

### Task 5: Source Trace — Data Integrity and Code Quality (Steps 6–7)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Steps 6 and 7

- [ ] **Step 1: Write Step 6 — Data Integrity**

  Replace `## Step 6: Source Trace — Data Integrity` with:

  ```markdown
  ## Step 6: Source Trace — Data Integrity

  Read view + model + any audit helpers. Tag findings `[INTEGRITY]`.

  - [ ] **Audit logging — create:** Every view that calls `db.session.add()` + `db.session.commit()`
        for a new record must call `log_create(module, record_id, identifier)` (or `log_audit(...)`)
        from `app/audit/utils.py`. Missing → HIGH.
  - [ ] **Audit logging — update:** Every update must call `log_update(...)` with both `old_values`
        and `new_values`. Use `get_changes(old_obj, new_data, fields)` to diff.
        Missing → HIGH. `new_values` only (no `old_values`) → MEDIUM.
  - [ ] **Audit logging — delete:** Every delete must snapshot the record first using
        `model_to_dict(obj, fields)` and pass it as `old_values` to `log_delete(...)`. Missing → HIGH.
  - [ ] **Transaction scope:** Are related writes (e.g., header + line items) committed in a single
        `db.session.commit()`? Multiple commits in sequence without rollback handling → MEDIUM.
  - [ ] **Approval workflow compliance:** If the entity is approval-gated (COA accounts, VAT categories,
        WHT codes), does the view create/update via the `*ChangeRequest` model rather than directly
        modifying the entity? Direct modification bypassing the workflow → CRITICAL.
  - [ ] **Cascade / orphan safety:** On delete of a parent record, are child records handled?
        Check for: SQLAlchemy `cascade='all, delete-orphan'` on the relationship, or an explicit
        pre-delete query that removes children, or a check that blocks deletion if children exist.
        Unhandled orphans → HIGH.
  - [ ] **Philippine Standard Time:** Every `datetime` field set in this view must use `ph_now()` or
        `ph_datetime(...)` from `app.utils`. Any bare `datetime.now()` or `datetime.utcnow()` → HIGH.
        ```python
        # Bad:
        bill.created_at = datetime.now()
        # Good:
        from app.utils import ph_now
        bill.created_at = ph_now()
        ```
  ```

- [ ] **Step 2: Write Step 7 — Code Quality**

  Replace `## Step 7: Source Trace — Code Quality (PEP 8 + Maintainability)` with:

  ```markdown
  ## Step 7: Source Trace — Code Quality (PEP 8 + Maintainability)

  Read view + template. Tag findings `[QUALITY]`.

  **PEP 8:**
  - [ ] Line length: any lines > 100 characters? (≤79 preferred, ≤99 acceptable for Flask views) → LOW
  - [ ] Naming: variables and functions `snake_case`; classes `PascalCase`; constants `UPPER_CASE` → LOW
  - [ ] Spacing: operators surrounded by spaces (`x = a + b`), commas followed by space → LOW
  - [ ] Blank lines: two blank lines between top-level functions; one between methods → LOW
  - [ ] Imports: standard lib first, then third-party, then local; no wildcard `from x import *` → LOW

  **Maintainability:**
  - [ ] **Function length:** View functions > ~50 lines doing multiple unrelated things → MEDIUM.
        Propose extracting a helper (e.g., `_build_bill_summary(items)`).
  - [ ] **Deep nesting:** `if` inside `if` inside `for` (3+ levels) → MEDIUM.
  - [ ] **Dead code:** Commented-out blocks or unused imports → LOW.
  - [ ] **Magic literals:** Hardcoded strings/numbers that appear > once or have business meaning
        (e.g., `status='posted'` scattered in 4 places vs. a constant `STATUS_POSTED = 'posted'`) → LOW.
  - [ ] **Docstrings:** Public view functions missing a one-line docstring describing what the route does
        → LOW. (Do NOT add "what the code does" comments — only docstrings on public functions.)
  - [ ] **Template complexity:** Jinja2 template with significant Python-style logic (complex
        calculations, string building, multi-level conditionals) that belongs in the view → MEDIUM.
  - [ ] **Duplication:** Logic in this view that appears nearly identical in a sibling view and could
        be a shared helper in `app/<feature>/utils.py` → MEDIUM.
  ```

- [ ] **Step 3: Spot-check**

  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 310 lines.

---

### Task 6: Impact Analysis (Step 8)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Step 8

- [ ] **Step 1: Write Step 8 — Impact Analysis**

  Replace `## Step 8: Impact Analysis` with:

  ```markdown
  ## Step 8: Impact Analysis

  For every finding that touches a **shared function, model method, utility, or base template**,
  assess downstream effects before writing the report.

  Work through each finding that modifies shared code and ask:

  1. **Who else calls this?**
     Grep for the function/method name across all blueprints:
     ```
     Grep pattern: <function_name>
     glob: app/**/*.py
     ```
     List every caller. If more than this one view is affected, note "Impact: also affects <list>".

  2. **Dependent reports or exports:**
     If a model field is added/removed/renamed, check:
     - `app/reports/views.py` — does any report query this field?
     - `app/utils/export.py` — does `export_to_excel` / `export_to_csv` reference it?
     If yes → append "Impact: update reports/export column mapping."

  3. **Audit trail snapshot consistency:**
     If a model field changes, check that `model_to_dict(obj, fields)` in the delete audit
     and `get_changes(old_obj, new_data, fields)` in the update audit include the updated field list.
     If not → append "Impact: update audit snapshot field list."

  4. **Approval workflow change_data schema:**
     If an approval-gated entity's fields change, existing pending `*ChangeRequest` rows may have
     stale JSON in `change_data`. Note: "Impact: existing pending change requests may need migration."

  5. **Test coverage gap:**
     Is the affected view/function covered by a test in `tests/`?
     Grep: `tests/` for the view function name or route path.
     If no test exists → append "Impact: no test coverage — add test after fix."

  **How to surface impacts in the report:**
  Impact items are **not separate findings**. Append them as a sub-item on the parent finding:
  ```
  FINDING-003 [HIGH] Missing ph_now() in journal_entry create
    File: app/journal_entries/views.py:45
    Fix:  Replace datetime.now() with ph_now() from app.utils
    Impact: Same pattern in app/purchase_bills/views.py:88 and app/receipts/views.py:62 — fix all three.
  ```

  The Impact section of the report lists only findings whose impact spans **other pages or modules**
  (not just a one-line fix in the same file).
  ```

- [ ] **Step 2: Spot-check**

  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 370 lines.

---

### Task 7: Report Format and Severity Reference (Step 9 + Severity)

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page.md` — fill in Step 9 and Severity Reference

- [ ] **Step 1: Write Step 9 — Report**

  Replace `## Step 9: Report` with the following (the backtick fence below uses 4 backticks to
  avoid closing prematurely — write it with 3 backticks in the actual file):

  ````markdown
  ## Step 9: Report

  Print the full report to the terminal. Structure exactly as shown below.

  ```
  ════════════════════════════════════════════════════
  PAGE ANALYSIS REPORT
  URL:      <resolved_url>
  Page:     <page_title>  (<endpoint function name>)
  Files:    <comma-separated list of source files read>
  ────────────────────────────────────────────────────

  [1] UI
    FINDING-001 [HIGH]   <one-line description>
      File: <path>:<line>
      Fix:  <one sentence or before/after snippet>

    FINDING-002 [LOW]    <one-line description>
      File: <path>:<line>
      Fix:  <...>

  [2] UX
    ...

  [3] SECURITY
    ...

  [4] QUERIES
    ...

  [5] DATA INTEGRITY
    ...

  [6] CODE QUALITY
    ...

  [7] IMPACT
    (Cross-module impacts only — items already listed under their parent finding above.
     Repeat here only if the impact spans a different page or module.)
    FINDING-NNN [HIGH]   <description>
      Impact: <list of other affected files/modules>

  ────────────────────────────────────────────────────
  PRIORITIZED ACTION PLAN  (top 5 by impact)
    1. [CRITICAL/HIGH] <description>  → fix in: <file>
    2. [HIGH]          <description>  → fix in: <file>
    3. [HIGH]          <description>  → fix in: <file>
    4. [MEDIUM]        <description>  → fix in: <file>
    5. [MEDIUM]        <description>  → fix in: <file>

  SUMMARY
    Critical: N  |  High: N  |  Medium: N  |  Low: N
    Total findings: N

  SKILL IMPROVEMENT NOTES
    Patterns or checks found this run not currently in this skill's checklist:
    - <observation>
    (none if nothing new surfaced)
  ════════════════════════════════════════════════════
  ```

  **Rules:**
  - Number findings sequentially across all dimensions: FINDING-001, FINDING-002, etc.
  - If a dimension has no findings, write: `  (none)`
  - The Prioritized Action Plan always lists exactly 5 items; if fewer than 5 findings exist, list all.
  - Severity ordering within each dimension: CRITICAL → HIGH → MEDIUM → LOW.
  - Impact sub-items are indented under their parent finding and start with `Impact:`.
  ````

- [ ] **Step 2: Write Severity Reference**

  Replace `## Severity Reference` with:

  ```markdown
  ## Severity Reference

  | Level | Meaning | Examples |
  |-------|---------|---------|
  | CRITICAL | Data loss, security breach, or broken core workflow | Missing `@login_required`, JS `confirm()` popup, missing CSRF token, bypass of approval workflow |
  | HIGH | Wrong behavior, missing audit log, significant UX failure | Missing role check on write, N+1 query, missing `ph_now()`, unfiltered list query leaking cross-branch data |
  | MEDIUM | Sub-optimal but functional; noticeable friction | Unbounded query, deep nesting, multi-step task that should be one step, template business logic |
  | LOW | Style, minor inconsistency, future-proofing | PEP 8 line length, missing docstring, magic literal, dead code |
  ```

- [ ] **Step 3: Final line count check**

  Run: `(Get-Content "C:\Users\user\.claude\skills\analyze-page.md" | Measure-Object -Line).Lines`
  Expected: more than 420 lines.

---

### Task 8: Live Smoke Run

**Purpose:** Verify the skill produces a correctly structured report on a real CAS page.

**Pre-condition:** Flask dev server running at `http://127.0.0.1:5000`. Use `/launch` if needed.

- [ ] **Step 1: Start the server if not already running**

  ```powershell
  $result = netstat -ano | findstr ":5000 " | findstr "LISTENING"
  if (-not $result) { Write-Host "Server not running — use /launch first" }
  else { Write-Host "Server is running" }
  ```

- [ ] **Step 2: Invoke the skill on the vendor list page**

  Type `/analyze-page http://127.0.0.1:5000/vendors` in the chat and run the skill.

  **Check that the report output contains all of these:**
  - [ ] Header block with URL, Page title, Files list
  - [ ] Sections [1] UI through [7] IMPACT (all 7 present, even if some say "(none)")
  - [ ] PRIORITIZED ACTION PLAN block
  - [ ] SUMMARY line with counts
  - [ ] SKILL IMPROVEMENT NOTES section

- [ ] **Step 3: Verify no placeholder text leaked into the output**

  The report must not contain: "TBD", "TODO", `<endpoint function name>` (unreplaced template text),
  or empty `File:` lines.

- [ ] **Step 4: Record result**

  If the report structure is correct → skill implementation complete.
  If any section is missing or malformed → fix the corresponding skill section (Tasks 2–7) and re-run.
