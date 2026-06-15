# analyze-page v2: Page-Type Checklists + Run History

## Goal

Two improvements to the `/analyze-page` skill:

- **B — Page-type-aware checklists:** The skill auto-detects which of five page types a page is (list / form / detail / auth / report) and runs additional dimension-specific checks on top of the standard checklist.
- **D — Run history:** Findings are fingerprinted and stored per URL in `.analyze-page/<slug>.json`. Every re-run shows a DELTA section (NEW / PERSISTED / RESOLVED) compared to the prior run.

---

## B: Page Type Detection

Detection runs in Step 0c (after navigation), using two signals in order.

**Signal 1 — URL pattern (checked first):**

| URL pattern | Detected type |
|---|---|
| path ends in `/create` | `form` |
| path matches `/<resource>/<int>/edit` | `form` |
| path is `/login`, `/register`, `/select-branch` | `auth` |
| path matches `/<resource>/<int>` (no `/edit`) | `detail` |
| path starts with `/reports` or `/dashboard` | `report` |
| path matches `/<resource>` (no trailing ID) | `list` |

**Signal 2 — Snapshot (used when URL pattern is ambiguous):**

| Snapshot signal | Detected type |
|---|---|
| Has `<table>` element | `list` |
| Has `<form>` with multiple input types | `form` |
| Has username + password fields only | `auth` |
| Has summary/totals, no table, no form | `report` |

If still ambiguous after both signals, the skill asks one clarifying question before proceeding.

Detected type is recorded in working notes:
```
Page type: auth   (detected: URL pattern match)
```

---

## B: Page-Type-Specific Checklist Additions

Additional checks run **on top of** the standard 8-dimension checklist — existing checks always run regardless of type. Items are tagged with their type so the reason for inclusion is clear.

### `list` pages

- `[QUERY]` Is `.paginate()` or `.limit()` used? Unbounded `.all()` on a growing table → MEDIUM
- `[QUERY]` Any search/filter that concatenates user input into a raw SQL string → HIGH
- `[SECURITY]` Is every list query filtered by `session['selected_branch_id']`? → HIGH if not
- `[UI]` Is there an empty-state message when the list has zero rows?

### `form` (create/edit) pages

- `[ATTACK]` Any `**request.form`, `**form.data`, or `__dict__.update(...)` pattern → CRITICAL
- `[INTEGRITY]` On edit: is `get_changes(old_obj, new_data, fields)` called before commit? → HIGH if not
- `[INTEGRITY]` On create: are role-sensitive fields (`role`, `is_active`, `branch_id`) absent from the form or blocked for non-admin? → CRITICAL if exposed
- `[UX]` On validation failure, does the form re-render with the user's entered values intact?

### `detail` pages

- `[SECURITY]` Does the view verify `record.branch_id == session['selected_branch_id']` (or equivalent)? → HIGH if not
- `[UI]` Are edit/delete actions hidden or disabled in the template for roles that cannot use them?
- `[UX]` If there is a delete action, is it an HTML modal — not a JS `confirm()` — with `{{ csrf_token() }}`? → CRITICAL if JS popup

### `auth` pages

The full Step 4b (Attacker Perspective) checklist already covers this type comprehensively. No additional items needed.

### `report/dashboard` pages

- `[QUERY]` Are aggregations (`SUM`, `COUNT`, `GROUP BY`) done at the database level (SQLAlchemy aggregates) or Python level (summing a `.all()` result)? Python-level on large tables → HIGH
- `[QUERY]` Are report queries bounded by date range and/or branch? Unbounded aggregation → MEDIUM
- `[UI]` Is there a "no data" message when the report returns zero rows?
- `[INTEGRITY]` Do report totals match what you would get summing the source documents? Flag as: "manual spot-check recommended"

---

## D: Run History

### Storage

**Location:** `.analyze-page/<slug>.json` — one file per URL, gitignored.

**Slug derivation:** URL path → replace `/` with `_`, strip leading/trailing underscores, replace numeric IDs with `id`.

Examples:
- `/login` → `login.json`
- `/purchase-bills/3/edit` → `purchase-bills_id_edit.json`
- `/vendors` → `vendors.json`

On first run, the skill creates `.analyze-page/` and appends `/.analyze-page/` to `.gitignore` if not already present.

Last 5 runs are kept; the oldest is dropped when a sixth is written.

### JSON Schema

```json
{
  "url_path": "/login",
  "page_type": "auth",
  "runs": [
    {
      "run_id": "2026-06-13T08:38:38",
      "findings": [
        {
          "fingerprint": "7f3a9c",
          "dimension": "ATTACKER PERSPECTIVE",
          "severity": "HIGH",
          "description": "Account lockout bypass via case-variant usernames",
          "file": "app/users/views.py",
          "line": 146
        }
      ]
    }
  ]
}
```

### Finding Fingerprint

A 6-character hash of:
```
"{dimension}|{severity}|{file_path}|{first_8_space_delimited_tokens_of_description_lowercased}"
```

Line number is intentionally excluded so fingerprints survive line shifts from unrelated edits. Two findings match across runs if their fingerprints match.

### Delta Comparison

Computed at the end of Step 9 by comparing this run's fingerprints against the most recent prior run's fingerprints:

- **NEW:** fingerprint present in this run, absent in prior run
- **PERSISTED:** fingerprint present in both; count how many consecutive prior runs it appeared in
- **RESOLVED:** fingerprint present in prior run, absent in this run

RESOLVED findings are still checked on every run — RESOLVED means "the check ran and the issue was not detected," not "this check is skipped."

### Delta Report Section

Added to the report between SUMMARY and SKILL IMPROVEMENT NOTES:

```
DELTA (vs. run 2026-06-10T14:22:11)
  NEW:        2 findings  → FINDING-001, FINDING-003
  PERSISTED:  3 findings  → FINDING-002 (4 runs), FINDING-004 (2 runs), FINDING-005 (1 run)
  RESOLVED:   1 finding   → "Missing @login_required on /vendors/create"
```

If no prior run exists:
```
DELTA: first run for this page — no prior findings to compare.
```

---

## Skill Flow Changes

| Step | Change |
|---|---|
| Step 0c (Merge) | Detect page type; load prior run from `.analyze-page/<slug>.json` if it exists |
| Steps 2–7 | Each dimension checks `page_type` and runs the additional type-specific items |
| Step 9 (Report) | Print DELTA section after SUMMARY; write updated history file after report is printed |

Working notes gain two new fields in Step 0c:
```
Page type: auth    (detected: URL pattern match)
Prior run: 2026-06-10T14:22:11  (7 findings — loaded)
```

No changes to Steps 1, 4b, or 8. The Explore agent dispatch in Step 0b is unchanged.

---

## Out of Scope

- Finding suppression (marking false positives as permanently ignored) — Approach 3, not needed yet
- Trend charts or multi-run history views
- Cross-page finding aggregation
- CI/CD integration
