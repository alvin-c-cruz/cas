# analyze-page v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `/analyze-page` skill with (B) auto-detected page-type-specific checklist items and (D) per-URL run history with a DELTA section that shows NEW / PERSISTED / RESOLVED findings on re-runs.

**Architecture:** All changes are edits to one file — `C:\Users\user\.claude\skills\analyze-page\SKILL.md`. The plan is broken into four additive tasks: page-type detection in Step 0c, prior-run loading in Step 0c, type-specific checklist items across Steps 2–7, and the delta report + history write in Step 9. Each task is self-contained and verifiable by reading the edited file.

**Tech Stack:** Markdown editing of `SKILL.md`. No Python, no migrations, no tests (the "test" for each task is reading the file and confirming the exact text is present).

---

### Task 1: Add page-type detection to Step 0c

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page\SKILL.md` — Step 0c section

The current Step 0c ends with a working-notes block. We insert the page-type detection block immediately after that block, before the end of Step 0c.

- [ ] **Step 1: Read the current Step 0c section**

Open `C:\Users\user\.claude\skills\analyze-page\SKILL.md` and locate Step 0c. Confirm it ends with:

```
Page type: <type>   (detected: <URL pattern match | snapshot signal | user input>)
Prior run: <...>
```
or with the existing working-notes block that does NOT yet mention page type. Note the exact closing text so you know where to insert.

- [ ] **Step 2: Insert the page-type detection block**

In `C:\Users\user\.claude\skills\analyze-page\SKILL.md`, find the working-notes block in Step 0c:

```
**Record working notes:**
```
Endpoint:  <function_name>  (<blueprint_name>)
Template:  <path>
Model(s):  <list>
Form(s):   <list>
Helpers:   <list>
```
```

Replace it with:

```
**Record working notes:**
```
Endpoint:  <function_name>  (<blueprint_name>)
Template:  <path>
Model(s):  <list>
Form(s):   <list>
Helpers:   <list>
Page type: <type>   (detected: URL pattern | snapshot | user input)
Prior run: <run_id  (N findings)  |  none — first run>
```

### Page type detection

Detect page type immediately after recording `resolved_url`. Check Signal 1 first; only use Signal 2 if Signal 1 is ambiguous.

**Signal 1 — URL pattern (first match wins):**

| URL pattern | Detected type |
|---|---|
| path ends in `/create` | `form` |
| path contains `/<int>/edit` (digit segment before `/edit`) | `form` |
| path is `/login`, `/register`, or `/select-branch` | `auth` |
| path contains `/<int>` with no `/edit` suffix | `detail` |
| path starts with `/reports` or `/dashboard` | `report` |
| all other single-segment paths | `list` |

**Signal 2 — Snapshot (only when Signal 1 is ambiguous):**

| Snapshot signal | Detected type |
|---|---|
| Contains `<table>` element | `list` |
| Contains `<form>` with multiple distinct input types | `form` |
| Contains username + password fields and nothing else | `auth` |
| Contains summary totals, no table, no form | `report` |

If still ambiguous after both signals, ask the user: **"What type is this page — list, form, detail, auth, or report?"**

Record the result in working notes:
```
Page type: auth   (detected: URL pattern match)
```
```

- [ ] **Step 3: Verify**

Read the file. Confirm the page-type detection table, Signal 1, Signal 2, and the updated working-notes block are all present in Step 0c.

- [ ] **Step 4: Commit**

```
The skill file is outside the CAS git repo — no commit needed. Task is complete once the file is saved and verified.
```

---

### Task 2: Add prior-run loading to Step 0c

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page\SKILL.md` — Step 0c section, after page-type detection block

- [ ] **Step 1: Locate insertion point**

In Step 0c, find the end of the page-type detection block you just added (ends with the `Page type: auth (detected: URL pattern match)` example line). Insert the prior-run loading block immediately after it.

- [ ] **Step 2: Insert the prior-run loading block**

Add this section after the page-type detection block in Step 0c:

```
### Prior run loading

Compute the **URL slug** from `url_path`:
1. Replace any digit-only path segments with `id`
   → `/purchase-bills/3/edit` becomes `/purchase-bills/id/edit`
2. Replace every `/` with `_`
   → `_purchase-bills_id_edit`
3. Strip leading and trailing underscores
   → `purchase-bills_id_edit`
4. The history file path is: `.analyze-page/<slug>.json`

**If `.analyze-page/<slug>.json` exists:**
- Parse the JSON and load the `runs` array
- Take the most recent entry (last item in `runs`)
- Record in working notes: `Prior run: <run_id>  (<N> findings — loaded)`
- Keep this run's findings in memory for the delta comparison in Step 9

**If the file does not exist:**
- Record in working notes: `Prior run: none — first run for this page`
- No delta comparison will be performed in Step 9
```

- [ ] **Step 3: Verify**

Read the file. Confirm the slug-computation steps (4 numbered steps), the conditional file-load logic, and the two working-notes examples are present.

- [ ] **Step 4: Commit**

```
The skill file is outside the CAS git repo — no commit needed. Task is complete once the file is saved and verified.
```

---

### Task 3: Add type-specific checklist items to Steps 2–7

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page\SKILL.md` — end of Steps 2, 3, 4, 4b, 5, and 6

Add a `### Type-specific additions` subsection at the **end** of each relevant step (before the next `## Step` heading). Step 7 (Code Quality) gets no type-specific additions — quality checks are type-agnostic.

- [ ] **Step 1: Add type-specific items to Step 2 (UI)**

Locate the end of the `## Step 2: Browser Pass — UI` section (the last `- [ ]` item before `## Step 3`). Append:

```
### Type-specific UI checks

**If `page_type == 'list'`:**
- [ ] Is there an empty-state message (not a blank table body) when the list has zero rows?

**If `page_type == 'detail'`:**
- [ ] Are edit and delete action buttons hidden or disabled in the template for roles that cannot use them?

**If `page_type == 'report'`:**
- [ ] Is there a "no data" message when the report returns zero rows?
```

- [ ] **Step 2: Add type-specific items to Step 3 (UX)**

Locate the end of `## Step 3: Browser Pass — UX` (last `- [ ]` before `## Step 4`). Append:

```
### Type-specific UX checks

**If `page_type == 'form'`:**
- [ ] On validation failure, does the form re-render with the user's entered values intact (not blank)?

**If `page_type == 'detail'`:**
- [ ] If there is a delete action, is it an HTML modal with `{{ csrf_token() }}` — NOT a JS `confirm()` popup? → CRITICAL if JS popup.
```

- [ ] **Step 3: Add type-specific items to Step 4 (Security)**

Locate the end of `## Step 4: Source Trace — Security` (last `- [ ]` before `## Step 4b`). Append:

```
### Type-specific security checks

**If `page_type == 'list'`:**
- [ ] Is every list query filtered by `session['selected_branch_id']`?
      ```python
      # Expected:
      records = Model.query.filter_by(branch_id=session['selected_branch_id']).all()
      ```
      Missing branch filter → HIGH.

**If `page_type == 'form'`:**
- [ ] Are role-sensitive fields (`role`, `is_active`, `branch_id`) absent from the WTForms form class
      or blocked for non-admin in the view before commit?
      Exposed on a non-admin form → CRITICAL.

**If `page_type == 'detail'`:**
- [ ] Does the view verify `record.branch_id == session.get('selected_branch_id')` before rendering?
      Missing ownership check → HIGH.
```

- [ ] **Step 4: Add type-specific items to Step 4b (Attacker Perspective)**

Locate the end of `## Step 4b: Attacker Perspective` (last `- [ ]` before `## Step 5`). Append:

```
### Type-specific attacker checks

**If `page_type == 'form'`:**
- [ ] **Mass assignment (form emphasis):** Scan every POST handler for `**request.form`,
      `**form.data`, or `model.__dict__.update(...)`. A single mass-assignment pattern
      on a write form can override role, status, or branch. → CRITICAL if found.
```

- [ ] **Step 5: Add type-specific items to Step 5 (Queries)**

Locate the end of `## Step 5: Source Trace — Queries` (last `- [ ]` before `## Step 6`). Append:

```
### Type-specific query checks

**If `page_type == 'list'`:**
- [ ] Is `.paginate()` or `.limit()` applied to the main list query?
      Unbounded `.all()` on a growing table → MEDIUM.
- [ ] Is there a search or filter feature? Confirm user input is passed through WTForms
      validators into `.filter_by()` — never concatenated into a raw SQL string via
      `text(f"... {val}")`. Raw concatenation → HIGH.

**If `page_type == 'report'`:**
- [ ] Are aggregations (`SUM`, `COUNT`, `GROUP BY`) done at the **database level** using
      SQLAlchemy aggregate functions (`func.sum`, `func.count`) rather than Python iteration
      over `.all()`? Python-level aggregation on large tables → HIGH.
      ```python
      # Bad — loads all rows into Python:
      total = sum(bill.amount for bill in PurchaseBill.query.all())
      # Good — aggregation in the DB:
      from sqlalchemy import func
      total = db.session.query(func.sum(PurchaseBill.amount)).scalar()
      ```
- [ ] Are report queries bounded by **both** a date range and a branch filter?
      Unbounded cross-branch aggregation → MEDIUM.
```

- [ ] **Step 6: Add type-specific items to Step 6 (Data Integrity)**

Locate the end of `## Step 6: Source Trace — Data Integrity` (last `- [ ]` before `## Step 7`). Append:

```
### Type-specific integrity checks

**If `page_type == 'form'` and the route is an edit (URL contains `/<int>/edit`):**
- [ ] Is `get_changes(old_obj, new_data, fields)` called **before** `db.session.commit()`
      to capture the old-vs-new diff for the audit log?
      ```python
      # Expected pattern:
      old_values = model_to_dict(record, fields)
      record.field = form.field.data
      db.session.commit()
      log_update(..., old_values=old_values,
                 new_values=model_to_dict(record, fields))
      ```
      Missing pre-update snapshot → HIGH.

**If `page_type == 'report'`:**
- [ ] Do report totals appear consistent with what you would get by summing the source
      documents manually? Flag as: `[INTEGRITY] Manual spot-check recommended — verify
      report totals against source documents.`
```

- [ ] **Step 7: Verify all six type-specific subsections**

Read `SKILL.md`. Confirm `### Type-specific` subsections appear at the end of Steps 2, 3, 4, 4b, 5, and 6. Confirm Step 7 has no such subsection.

- [ ] **Step 8: Commit**

```
The skill file is outside the CAS git repo — no commit needed. Task is complete once the file is saved and verified.
```

---

### Task 4: Add delta report section and history write to Step 9

**Files:**
- Modify: `C:\Users\user\.claude\skills\analyze-page\SKILL.md` — Step 9 report template and instructions

- [ ] **Step 1: Add DELTA section to the report template**

In Step 9, locate the report template's SUMMARY block:

```
SUMMARY
  Critical: N  |  High: N  |  Medium: N  |  Low: N
  Total findings: N

SKILL IMPROVEMENT NOTES
```

Replace it with:

```
SUMMARY
  Critical: N  |  High: N  |  Medium: N  |  Low: N
  Total findings: N

DELTA (vs. run <prior_run_id>)
  NEW:        N findings  → FINDING-001, FINDING-003
  PERSISTED:  N findings  → FINDING-002 (4 runs), FINDING-004 (2 runs)
  RESOLVED:   N findings  → "<short description of resolved finding>"

SKILL IMPROVEMENT NOTES
```

If no prior run exists, replace the DELTA block with a single line:
```
DELTA: first run for this page — no prior findings to compare.
```

- [ ] **Step 2: Add delta computation instructions**

In Step 9, after the report template block and **Rules** list, add a new section:

```
## Delta computation

Before printing the DELTA section, compute the diff between this run's findings and the
most recent prior run (loaded in Step 0c).

**Fingerprint each finding** as a 6-character hash of:
```
"{dimension}|{severity}|{file_path}|{first_8_space_delimited_tokens_of_description_lowercased}"
```
Example: `"ATTACKER PERSPECTIVE|HIGH|app/users/views.py|account lockout bypass via case variant"`
→ fingerprint: `7f3a9c`

**Classify each finding:**
- **NEW:** fingerprint present in this run, absent in prior run's findings
- **PERSISTED:** fingerprint present in both runs; count consecutive prior runs it appeared in
- **RESOLVED:** fingerprint present in prior run, absent in this run

RESOLVED findings are still checked on every run. RESOLVED means "the check ran and the issue
was not detected this time" — it does not suppress future checks.

## History file write

After printing the full report, write the updated history file.

**Setup (first run only):**
1. If `.analyze-page/` directory does not exist, create it
2. If `.gitignore` does not contain `.analyze-page/`, append `.analyze-page/` to `.gitignore`

**Write the run entry** to `.analyze-page/<slug>.json`:

```json
{
  "url_path": "<url_path>",
  "page_type": "<page_type>",
  "runs": [
    {
      "run_id": "<ISO-8601 timestamp of this run>",
      "findings": [
        {
          "fingerprint": "<6-char hash>",
          "dimension": "<dimension name>",
          "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
          "description": "<one-line finding description>",
          "file": "<file_path>",
          "line": <line_number_or_null>
        }
      ]
    }
  ]
}
```

If the file already exists, load it, append the new run to `runs`, and if `runs` now has more
than 5 entries drop the oldest (first) entry before writing.
```

- [ ] **Step 3: Verify**

Read the file. Confirm:
- DELTA block appears between SUMMARY and SKILL IMPROVEMENT NOTES in the report template
- Delta computation section is present with the fingerprint formula
- History file write section is present with the JSON schema and the 5-run cap rule
- `.gitignore` setup instruction is present

- [ ] **Step 4: Commit**

```
The skill file is outside the CAS git repo — no commit needed. Task is complete once the file is saved and verified.
```

---

## Self-Review Checklist

After all tasks are complete, verify spec coverage:

| Spec requirement | Covered by task |
|---|---|
| 5 page types auto-detected from URL + snapshot | Task 1 |
| Ambiguous detection falls back to user question | Task 1 |
| Page type recorded in working notes | Task 1 |
| Slug derivation (digit → id, / → _, strip underscores) | Task 2 |
| Prior run loaded from `.analyze-page/<slug>.json` | Task 2 |
| Prior run recorded in working notes | Task 2 |
| list: empty-state, branch scoping, pagination, raw SQL | Tasks 3 |
| form: mass assignment, role-sensitive fields, audit snapshot, UX re-population | Task 3 |
| detail: ownership check, role-gated buttons, HTML modal | Task 3 |
| report: DB-level aggregation, bounded queries, no-data message, spot-check note | Task 3 |
| DELTA section in report (NEW / PERSISTED / RESOLVED) | Task 4 |
| Fingerprint formula | Task 4 |
| History file write with 5-run cap | Task 4 |
| `.analyze-page/` created and gitignored on first run | Task 4 |
| RESOLVED findings still checked every run | Task 4 |
