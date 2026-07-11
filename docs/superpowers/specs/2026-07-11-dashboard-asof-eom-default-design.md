# Dashboard "As of Date" defaults to month-end (BUG-DASHBOARD-ASOF-DEFAULT-EOM)

**Date:** 2026-07-11
**Severity:** Low (UX / reporting default — owner-flagged)
**Status:** Design approved, pending implementation

## Problem

The Dashboard "As of Date" picker defaults to today. The current view
(`app/dashboard/views.py:31,39,41`) sets `today = ph_now().date()` and uses it as
the fallback when the `as_of_date` query param is absent or invalid; the template
(`app/dashboard/templates/dashboard/index.html:23,27`) seeds the input value and the
reset button off that value.

The owner wants the dashboard's financial snapshot to default to the natural
month-end reporting date (consistent with the EOM two-column IS/CF), not to the
arbitrary current day.

## Decisions (owner)

1. **Which month's end:** end of the **current** month (e.g. today 2026-07-11 →
   default 2026-07-31, a future date). This captures all of the current month's
   activity and keeps MTD/YTD on the current month. Future-dated defaults are already
   permitted by the existing "Allow any date — past, present, or future" logic.
2. **Reset button:** rename `📅 Today` → `📅 Month End` and have it reset the picker
   to end-of-current-month (the new default). The separate "today" quick-jump is
   dropped.

## Behavior change

| Case | Before | After |
|---|---|---|
| Default (no / invalid `as_of_date`) | today | **end of current month** |
| Reset button | `📅 Today` → snaps to today | `📅 Month End` → snaps to EOM |
| Explicit valid `as_of_date` param | honored | honored (unchanged) |

## Implementation

### View — `app/dashboard/views.py::home`
- Compute EOM from PH-now:
  ```python
  import calendar
  n = ph_now().date()
  eom = n.replace(day=calendar.monthrange(n.year, n.month)[1])
  ```
- Replace both `as_of_date = today` fallbacks (currently lines 39, 41) with
  `as_of_date = eom`.
- Replace the template kwarg `today=today.strftime('%Y-%m-%d')` with
  `month_end=eom.strftime('%Y-%m-%d')`. The `today` local becomes unused and is
  removed.
- `current_year` / `current_month` continue to derive from `as_of_date`, so the
  MTD/YTD data helpers are unchanged.

### Template — `app/dashboard/templates/dashboard/index.html`
- Input `value="{{ as_of_date }}"` unchanged (now defaults to EOM).
- Button (currently lines 26–30): reset target `'{{ today }}'` → `'{{ month_end }}'`;
  label `📅 Today` → `📅 Month End`.

## Testing (TDD)

Render-assertions on `GET /dashboard` — this is a default-**render** bug, so it is
pinned at the render layer, not via a POST contract (same lesson as the
`csrf-only-render-drops-hidden-fields` family: a POST test that supplies values
directly structurally cannot catch a wrong default render).

1. **No `as_of_date`** → the rendered date input carries the EOM value (its day ==
   the last day of the current PH month; month/year == current PH month/year).
2. **Invalid `as_of_date`** (e.g. `as_of_date=not-a-date`) → falls back to EOM, HTTP
   200 (no 500).
3. **Explicit valid `as_of_date`** (e.g. `2026-03-15`) → that value is honored and
   rendered (regression guard that the new default does not clobber a real pick).
4. **Button** renders the `Month End` label and the `month_end` value (asserts the
   old `Today` reset target is gone).

Tests compute the expected EOM from `ph_now()` using the same `calendar.monthrange`
logic so the assertion tracks the real clock.

## Scope / non-goals

- No change to `app/dashboard/dashboard_data.py` helpers.
- No change to the `/action-items` or `/api/action-items` routes.
- No new dependency; `calendar` is stdlib.
