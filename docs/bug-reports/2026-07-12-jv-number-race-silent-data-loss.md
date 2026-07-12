# BUG-JV-NUMBER-RACE-SILENT-DATA-LOSS

**Severity:** Medium (real, reproducible concurrency bug — not a corner case)
**Status:** OPEN
**Discovered:** 2026-07-12, via `clients/cas/ui-tests/concurrency_jv_concurrent_create.py`
(built in response to an owner request to test "2-3 users creating a new record in the
same document at the same time").

## Summary

`app/journal_entries/views.py::create()` generates the next `entry_number` once, on the
**GET** that renders the create form (`generate_jv_number()`, line 190), and persists
whatever `entry_number` the submitted POST carries verbatim (line 115) — it is never
regenerated or re-checked at submit time. `JournalEntry.entry_number` carries a DB-level
`unique=True` constraint (`app/journal_entries/models.py:32`).

If 2-3 users open `/journal-entries/create` within the same window (before any of them
has committed), **all** of them see the identical suggested next number. Whoever's POST
commits first wins; every later POST hits the unique-constraint `IntegrityError`, caught
by the view's blanket `except Exception` (line 167) → rollback → generic flash:

> An error occurred while creating the journal entry. Please try again.

The user gets no indication their number collided with another user's, no automatic
renumber-and-retry — their fully-filled-out JV (lines, description, everything) is simply
discarded unless they notice the vague error and manually resubmit.

## Reproduction (verified live)

3 independent `uitest_ca` browser sessions (separate Playwright contexts, each with its
own login/cookies) each opened `/journal-entries/create`. All 3 pre-fetched the identical
`entry_number` (`JV-2026-07-0002`). All 3 POSTs (balanced 2-line JV: 1610 debit / 4110
credit, 100.00) were released through a `threading.Barrier(3)` so they reached the server
within milliseconds of each other.

Result:
- User 1 → HTTP 200 (form re-rendered, generic error)
- User 2 → HTTP 302 → `/journal-entries/3` (succeeded)
- User 3 → HTTP 200 (form re-rendered, generic error)
- DB: exactly 1 row committed for the 3 attempted creates.

The one invariant that DOES always hold: no duplicate `entry_number` was ever actually
committed (the DB constraint guarantees this) — this is data-loss-under-contention, not
data-corruption.

## Root cause

```python
# app/journal_entries/views.py, GET branch of create()
form.entry_number.data = generate_jv_number(current_branch_id)   # computed once, at page load

# app/journal_entries/views.py, POST branch of create()
entry = JournalEntry(
    entry_number=form.entry_number.data,   # whatever the form carried, unmodified
    ...
)
...
except Exception as e:
    ...
    db.session.rollback()
    flash('An error occurred while creating the journal entry. Please try again.', 'error')
```

`generate_jv_number` → `next_sequence_number(prefix)` (`app/journal_entries/utils.py`)
does `SELECT ... ORDER BY entry_number DESC LIMIT 1` and computes `+1` — a classic
read-then-write race with no locking, no re-check, and no retry.

## Scope check — likely not unique to JV

This numbering shape (compute at GET, trust at POST, no re-check) is conceptually the
same pattern flagged generally in memory `document-numbering-system` ("regenerate-then-
lock breaks lookups"). Not yet verified whether Sales Invoice / Accounts Payable / Cash
Disbursement / Cash Receipt share the exact same vulnerability (their number fields may
or may not carry a DB-unique constraint, and their create views may or may not
regenerate at submit time). **Needs a sibling grep before fixing just JV** — see memory
`feedback-grep-siblings-on-fix`.

## Fix options (needs approval — view-layer only, no model change either way)

1. **Bounded retry on IntegrityError:** catch the unique-constraint violation
   specifically (distinct from the generic `except Exception`), regenerate a fresh
   `entry_number`, and retry the commit once. Minimal-diff, keeps the GET-time preview
   as a genuine best-effort suggestion.
2. **Assign the number at submit-time, inside the same transaction as the insert:**
   removes the TOCTOU window entirely. The number shown on the create page becomes purely
   advisory/display — what's actually saved is computed fresh at commit. More robust
   (closes the race at its root) but changes the form's UX contract slightly (the number
   a user sees while filling the form may not be the one that ends up saved) — worth a
   design decision before implementing.

## TDD

- Browser-level regression guard already exists:
  `clients/cas/ui-tests/concurrency_jv_concurrent_create.py` — currently 1/2 checks
  passing (the DB-integrity invariant passes; the "all N concurrent creates committed"
  check fails BY DESIGN until this is fixed). Flip that check to a plain assertion once
  the fix lands.
- Recommended companion: an app-level pytest that forces two `db.session` transactions
  to interleave deterministically around `next_sequence_number()` (rather than relying on
  wall-clock timing) — faster and more reliable in CI. See `tests/unit/test_concurrency.py`
  for the existing lost-update-style test patterns to mirror.

## Related

- Memory `document-numbering-system`, `optimistic-lock-conditional-update` (adjacent but
  distinct — that guards EDITS via `row_version`; this document-numbering race has no
  equivalent guard for CREATE-time number assignment).
- `clients/cas/ui-tests/TEST-CASES.md` — new Tier item for concurrency testing.
