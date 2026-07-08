# EOM Reporting Date + Two-Column Income Statement & Cash Flow

- **Date:** 2026-07-08
- **Status:** Approved design — ready for implementation planning
- **Scope:** `projects/cas` financial-statement reports (Trial Balance, Balance Sheet, Income Statement, Cash Flow)
- **Origin:** Balance-sheet audit of the alvinccruz instance (2026-07-08) surfaced a mid-month
  cutoff distortion: an as-of-*today* Balance Sheet showed a cancellation reversal (dated 07-08)
  without the future-dated original it reverses (dated 07-10), misstating equity by ₱8,000 for any
  report date in the 08–09 Jul window. Defaulting reports to month-end removes the whole class of
  mid-month artifacts and matches how monthly statements are read.

## Goals

1. All four financial statements default their **reporting date to the end of the current month**
   (today 2026-07-08 → 2026-07-31), instead of "today".
2. The **Income Statement and Cash Flow** become **reporting-date-driven, two-column** reports:
   a **Current Month** column and a **Year-to-Date** column, both derived from the single
   reporting date.

## Non-goals

- BIR Sales/Purchases books are out of scope — they already default to the current month via
  `resolve_period(mode='month')` and have no "today" edge.
- Trial Balance and Balance Sheet keep their single-column structure; only their default date changes.
- No change to any report's underlying figures/classification logic — only the default date and,
  for IS/CF, the presentation of two periods.

## Decisions (locked with the user)

| Question | Decision |
| --- | --- |
| What does EOM resolve to? | **End of the current month** (includes not-yet-elapsed days of the month). |
| IS/CF default period | Reporting date = current month-end; two columns derived from it. |
| IS/CF date model | **Reporting-date-driven** — one date picker; the arbitrary `start_date`/`end_date` range picker is removed from IS/CF. |
| Cash Flow | Same two-column, reporting-date-driven model as the Income Statement. |

## Current state (as mapped)

- **Trial Balance** and **Balance Sheet** parse dates via `_tb_params()` in `app/reports/views.py`
  → default `as_of = date.today()` (param `as_of`). Used by the page, `/export/excel`, and `/print`.
- **Income Statement** and **Cash Flow** parse via `_is_params()` → default range
  `date(today.year, 1, 1)` → `date.today()` (params `start_date` / `end_date`). Both share `_is_params()`.
- `generate_income_statement(start, end, branch_id)` returns a type-driven dict:
  `{ period_start, period_end, sections[], net_sales, gross_profit, operating_income,
  income_before_tax, net_income }`. Each `section` = `{ key, label, sign, total, lines, subtotal_label?,
  subtotal? }`, where `lines` is a hierarchical `rollup(rows, accounts)` tree (each node carries
  `code`, `name`, `amount`, and optional children).
- `generate_cash_flow(start, end, branch_id, method='indirect')` returns an activity-sectioned dict.
- No `end_of_month` / month-end helper exists yet.

## Design

### 1. `end_of_month` utility (new)

Add a pure function to `app/utils` (alongside the PH-time helpers):

```python
import calendar
def end_of_month(d: date) -> date:
    """Last calendar day of d's month."""
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])
```

"Today" is sourced from `ph_now().date()` (CAS convention — never naive `date.today()`).

### 2. Default reporting date (all four statements)

- **`_tb_params()`** (Trial Balance + Balance Sheet): default `as_of = end_of_month(ph_now().date())`.
  Explicit `?as_of=YYYY-MM-DD` still honored unchanged. No structural change to these two reports.

- **New `_stmt_params()`** (Income Statement + Cash Flow): returns `(as_of, branch_id)` where
  `as_of` defaults to `end_of_month(ph_now().date())`, param name `as_of` (unified with TB/BS).
  The view derives the two column ranges from `as_of`:
  - **Current Month** = `[as_of.replace(day=1), as_of]`
  - **Year-to-Date** = `[date(as_of.year, 1, 1), as_of]`

  `_is_params()` is retired for IS/CF (removed once both views migrate to `_stmt_params()`).

- **Back-compat:** if a legacy `?end_date=` (or `?start_date=`) arrives on IS/CF, coerce
  `as_of = parse(end_date)` (falling back to the EOM default on parse failure) so old bookmarks and
  cross-report links keep working. `start_date` is otherwise ignored on IS/CF.

### 3. Two-column merge (IS + CF)

Each view calls its generator **twice** — once for the Current-Month range, once for the YTD range —
then merges into a single render structure carrying both amounts per line.

New helper in `app/reports/financial.py` (or a small `app/reports/two_column.py`):

```python
def merge_two_column(mtd: dict, ytd: dict) -> dict:
    """Union two single-period statement dicts (same generator, same section order)
    into a two-column structure. Sections are aligned by section key (identical
    across both calls). Within a section, lines are unioned by account `code`,
    recursively over the rollup tree; a line present in only one column is
    zero-filled on the other. Every line node gains `mtd_amount` and `ytd_amount`
    (replacing the single `amount`); every section gains `mtd_total`/`ytd_total`
    and, where present, `mtd_subtotal`/`ytd_subtotal`. Top-level summary figures
    (net_sales, gross_profit, operating_income, income_before_tax, net_income for
    the IS; the CF activity subtotals and net change in cash) are carried as
    `{mtd, ytd}` pairs."""
```

Merge properties:
- Section order and keys come from the shared section spec (`IS_SECTIONS` / the CF activity spec),
  so both calls produce parallel section lists — align by index/key, never by label text.
- Line union is keyed by account `code` and applied recursively so hierarchical rollup children
  align; missing side → `0.0`.
- The YTD reporting-period end equals the Current-Month end (`as_of`), so `net_income` (YTD) remains
  exactly the value the Balance Sheet and Year-End close already consume — **the merge does not
  change the YTD figure any consumer depends on.**

### 4. Templates, export, print

- **IS template** (`reports/income_statement.html`) and **CF template** (`reports/cash_flow.html`):
  replace the start→end range picker with a **single reporting-date picker** (labeled "Reporting
  date", bound to the view-passed `as_of`), and add a second amount column. Column headers:
  - Current Month → `"<Mon YYYY>"` (e.g., "Jul 2026")
  - Year-to-Date → `"YTD <year>"` (e.g., "YTD 2026")
- **Excel export** (`app/reports/statement_export.py`: `build_income_statement_xlsx`,
  `build_cash_flow_xlsx`) and **print** views: emit both columns with the same headers.
- **Trial Balance / Balance Sheet** templates: no structural change; the existing date input already
  binds to the view-passed date, which now defaults to month-end. (Verify the binding during
  implementation; fix if any input computes "today" independently.)

## Ripple / verification checklist

- Grep dashboard, report index, and any cross-links for IS/CF URLs carrying `start_date`/`end_date`
  and update them to `as_of` (back-compat coercion covers stragglers).
- Confirm each report template's date `<input value=…>` binds to the view-provided date, not a fresh
  `now`/today.
- Any code/test importing `_is_params` must move to `_stmt_params`.

## Testing (TDD)

Write tests before implementation.

1. **`end_of_month`** — Jan→31, Feb 2026 (non-leap)→28, Feb 2028 (leap)→29, Dec→31, and idempotence
   when the input is already month-end.
2. **`_tb_params` / `_stmt_params` defaults** — no params → `as_of` is the month-end of the PH "today";
   explicit `?as_of=` overrides; malformed `?as_of=` falls back to the EOM default; legacy
   `?end_date=` on IS/CF coerces to `as_of`.
3. **`merge_two_column`** — union with a line present in only MTD, only YTD, and both; zero-fill on the
   missing side; section order preserved; hierarchical children aligned; `net_income`/activity
   subtotals carried as `{mtd, ytd}`; YTD column equals a direct single-call YTD generation.
4. **View/default rendering** — GET `/reports/income-statement` and `/reports/cash-flow` with no params
   render two columns headed `"<Mon YYYY>"` and `"YTD <year>"` for the current month-end; explicit
   `?as_of=2026-06-30` renders "Jun 2026" + "YTD 2026". GET `/reports/balance-sheet` and
   `/reports/trial-balance` with no params default to month-end.
5. **Consumer safety** — Balance Sheet `net_income` (current year) and Year-End close are unchanged
   for a given `as_of` (the YTD figure is identical to the pre-change single-period YTD result).

## Touch points (summary)

| File | Change |
| --- | --- |
| `app/utils/__init__.py` | add `end_of_month` |
| `app/reports/views.py` | `_tb_params` EOM default; new `_stmt_params`; IS & CF views call generator twice + merge; retire `_is_params` for IS/CF |
| `app/reports/financial.py` (or new `two_column.py`) | `merge_two_column` helper |
| `app/reports/statement_export.py` | two-column Excel for IS & CF |
| `reports/income_statement.html`, `reports/cash_flow.html` | single-date picker + second amount column |
| IS/CF print templates | second amount column |
| `tests/…` | unit + view tests per the plan above |
