# BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS

(Filed initially as BUG-JV-NUMBER-RACE-SILENT-DATA-LOSS; renamed after the finding was
confirmed to affect all 5 Core documents, not just JV.)

**Severity:** Medium (real, reproducible concurrency bug — confirmed in all 5 of
JV/SI/AP/CD/CR, not a corner case)
**Status:** FULLY FIXED 2026-07-12, all 5 documents (local `main`, not pushed)
**Discovered:** 2026-07-12, via `clients/cas/ui-tests/concurrency_jv_concurrent_create.py`
(built in response to an owner request to test "2-3 users creating a new record in the
same document at the same time"), then explicitly extended to Sales Invoice / Accounts
Payable / Cash Disbursement / Cash Receipt per owner instruction ("extend").

## SI/AP/CD/CR fix (done) — including a hardening pass after finding a residual gap

The 4 parallel subagents' `fresh_number_if_collision()` pre-check (regenerate + re-render +
explanatory flash on a detected collision) left a real gap: it is check-then-act, so a
genuinely simultaneous double-request can pass the `SELECT` before either has committed,
reaching the actual `db.session.flush()` uncaught. Confirmed live by re-running the browser
probes against the merged subagent fixes and inspecting the actual HTTP response bodies of
the "losing" requests: they still showed the raw `sqlite3.IntegrityError` message, not the
friendly re-render.

Closed by adding `flush_or_suggest_fresh_number()` (`app/utils/concurrency.py`) as a required
backstop wrapping each view's `db.session.flush()` call. It checks the `IntegrityError`
specifically names the document's number column before treating it as this bug — `Cash
DisbursementVoucher` has an unrelated second unique constraint (`check_number` per
`cash_account_id`) that must never be misdiagnosed as a numbering race and silently
discarded. TDD-backed (`tests/unit/test_concurrency.py::TestFlushOrSuggestFreshNumber`,
including the "unrelated constraint must re-raise" case). Re-verified live after the fix:
every losing response now shows the fresh suggested number and explanatory flash, zero raw
exceptions, across all 4 documents.

## JV fix (done)

Added `commit_with_renumber_retry(entity, number_attr, generate_number, max_attempts=3)`
to `app/utils/concurrency.py` — on an `IntegrityError` at commit, regenerates the number
(inside `db.session.no_autoflush`, otherwise the generator's own query autoflushes the
still-colliding pending entity and raises again immediately) and retries, bounded at 3
attempts. Wired into `journal_entries/views.py::create()`.

TDD: `tests/integration/test_jv_number_race.py` — pre-commits a JournalEntry under the
number a fresh `generate_jv_number()` call would return, POSTs a create carrying that same
stale number, asserts it still succeeds with a fresh distinct number. RED confirmed before
the fix, GREEN after. Full suite: 2653 passed, 1 pre-existing unrelated failure
(`test_sidebar_nav.py` — documented test-ordering cache leak, confirmed unaffected via
stash + isolated rerun). Browser probe `concurrency_jv_concurrent_create.py` now asserts
2/2 (was 1/2) against the isolated server restarted on the fixed code.

SI/AP/CD/CR are unfixed — same root cause, same fix shape (the helper is reusable as-is;
AP/CD/CR's existing pre-check would need a decision on whether to keep it as a fast-path
alongside the retry, or drop it now that the retry makes it redundant).

## Summary

Every Core-5 document generates its next number once, on the **GET** that renders the
create form, and persists whatever the submitted POST carries verbatim — none of the 5
re-check or re-generate the number at submit time:

| Doc | Generator | GET-time call | POST persists at | Pre-check before insert? |
|---|---|---|---|---|
| JV | `generate_jv_number` (`journal_entries/utils.py`) | `journal_entries/views.py:190` | `views.py:115` | **No** — relies purely on the DB `unique=True` + a blanket `except Exception` (generic flash) |
| SI | `generate_invoice_number` (`sales_invoices/views.py:89`) | `views.py:785` | `views.py:729` | **No** — same generic-catch shape as JV (flash includes raw exception text) |
| AP | `generate_ap_number` (`accounts_payable/views.py:1679`) | `views.py:841` | `views.py:750` | **Yes** (`views.py:744`) — friendly "AP number ... already in use" message |
| CD | `generate_cdv_number` (`cash_disbursements/views.py:76`) | `views.py:933` | `views.py:~875` | **Yes** (`views.py:863`) — friendly "CD number ... is already in use" message |
| CR | `generate_crv_number` (`cash_receipts/views.py:75`) | `views.py:946` | `views.py:893` | **Yes** (`views.py:881`) — friendly "CR Number ... already exists" message |

Every number column carries a DB-level `unique=True`. The 2-way UX split (generic-catch vs.
friendly pre-check) does **not** change the underlying race: a `SELECT ... first()` pre-check
before the `INSERT` is check-then-act, not atomic with the commit, so it narrows the window
but does not close it.

If 2-3 users open a document's create form within the same window (before any of them has
committed), **all** of them see the identical suggested next number. Whoever's POST commits
first wins; every later POST either hits the unique-constraint `IntegrityError` (JV/SI — caught
by a blanket `except Exception`, generic or exception-text flash) or the pre-check catches the
collision with a friendlier message (AP/CD/CR) — either way, the user gets no automatic
renumber-and-retry, and their fully-filled-out document (lines, description, everything) is
simply discarded unless they notice the error and manually resubmit.

## Reproduction (verified live — all 5 documents, identical technique)

3 independent `uitest_ca` browser sessions (separate Playwright contexts, each with its own
login/cookies) each opened the relevant create form. In **every one of the 5 runs**, all 3
sessions pre-fetched the identical suggested number. All 3 POSTs were released through a
`threading.Barrier(3)` (fired via `requests.Session`, not Playwright — Playwright's sync API
can't safely be driven across threads) so they reached the server within milliseconds of each
other.

Result — identical shape in **every single document**:
- 1 of 3 → HTTP 302 (succeeded)
- 2 of 3 → HTTP 200 (form re-rendered, error — generic for JV/SI, specific-but-still-a-loss
  for AP/CD/CR)
- DB: exactly 1 row committed for each 3-attempted-create batch.

| Doc | Pre-fetched number (all 3 identical) | Committed | Spec |
|---|---|---|---|
| JV | `JV-2026-07-0002` | 1/3 | `concurrency_jv_concurrent_create.py` |
| SI | `00002` | 1/3 | `concurrency_si_concurrent_create.py` |
| AP | `AP-2026-07-0001` | 1/3 | `concurrency_ap_concurrent_create.py` |
| CD | `CD-2026-07-0001` | 1/3 | `concurrency_cd_concurrent_create.py` |
| CR | `00001` | 1/3 | `concurrency_cr_concurrent_create.py` |

The one invariant that always held: no duplicate number was ever actually committed in any
of the 5 (the DB constraint guarantees this) — this is data-loss-under-contention across the
board, not data-corruption.

## Root cause (JV shown; identical shape in SI/AP/CD/CR)

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

`generate_jv_number` → `next_sequence_number(prefix)` (`app/journal_entries/utils.py`) does
`SELECT ... ORDER BY entry_number DESC LIMIT 1` and computes `+1` — a classic read-then-write
race with no locking, no re-check, and no retry. SI's `generate_invoice_number` and AP/CD/CR's
equivalents follow the same `SELECT MAX/latest, +1` shape.

## Fix options (needs approval — view-layer only, no model change either way; same shape
applies to all 5 documents, worth fixing uniformly in one pass)

1. **Bounded retry on IntegrityError / pre-check collision:** catch the unique-constraint
   violation (or pre-check hit) specifically, regenerate a fresh number, and retry the commit
   once. Minimal-diff, keeps the GET-time preview as a genuine best-effort suggestion.
2. **Assign the number at submit-time, inside the same transaction as the insert:** removes
   the TOCTOU window entirely. The number shown on the create page becomes purely
   advisory/display — what's actually saved is computed fresh at commit. More robust (closes
   the race at its root) but changes each form's UX contract slightly (the number a user sees
   while filling the form may not be the one that ends up saved) — worth a design decision
   before implementing.

## TDD

- Browser-level regression guards already exist for all 5 documents:
  `clients/cas/ui-tests/concurrency_{jv,si,ap,cd,cr}_concurrent_create.py` — each currently
  1/2 checks passing (the DB-integrity invariant passes; the "all N concurrent creates
  committed" check fails BY DESIGN until fixed). Flip each to a plain assertion once its
  document's fix lands.
- Recommended companion: an app-level pytest that forces two `db.session` transactions to
  interleave deterministically around each number-generator function (rather than relying on
  wall-clock timing) — faster and more reliable in CI, and could cover all 5 with one
  parametrized test. See `tests/unit/test_concurrency.py` for the existing lost-update-style
  test patterns to mirror.

## Related

- Memory `document-numbering-system`, `optimistic-lock-conditional-update` (adjacent but
  distinct — that guards EDITS via `row_version`; this document-numbering race has no
  equivalent guard for CREATE-time number assignment).
- `clients/cas/ui-tests/TEST-CASES.md` — T1.11 concurrency-testing item.
