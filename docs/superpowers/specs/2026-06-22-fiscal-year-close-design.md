# Fiscal Year Close (Year-End Closing Entries + Retained Earnings) — Design

_Date: 2026-06-22 · Status: approved design, pre-implementation_

## Problem

CAS has no mechanism to close the books at year-end. The Chart of Accounts already
carries `30201 Retained Earnings` and `30301 Current-Year Earnings` (both Equity),
but nothing posts to them. The Balance Sheet and Cash Flow **compute** Retained
Earnings on the fly from the P&L (`app/reports/financial.py:280-296`), and the code
explicitly warns this would **double-count** if real closing entries were ever posted
to an RE account. We want a proper, auditable year-end close that posts closing
journal entries (moving the year's profit into Retained Earnings) and reconciles the
reports so they read posted RE for closed years while still computing the open year.

Scope is **annual** only. Monthly/period **locking** already exists in the
`periods` module and is unchanged — closing entries are a distinct, once-a-year event.

## Decisions (from brainstorming)

1. **Goal:** proper year-end close — post closing JEs so the books carry a real RE balance.
2. **Method:** Income Summary method. Close all nominal accounts into `30301 Current-Year
   Earnings` (the clearing/income-summary account), then close `30301 → 30201 Retained
   Earnings`. Both existing equity accounts get their intended role.
3. **Trigger:** a dedicated **"Close Fiscal Year"** action (with **Reopen**), separate
   from monthly period locking.
4. **Branch scope:** per-branch. The close runs for every active branch (one today; a
   2nd branch arrives in 2027), each branch's P&L closing into its own branch-tagged RE.
5. **Reports reconciliation:** closed-year-aware split — posted RE for the closed span,
   computed P&L for the open (not-yet-closed) span. Backward-compatible before the first close.

## Data model (approved)

One new table, `fiscal_year_closes` (model in a new `app/periods/` or dedicated
`app/year_end/` package — see Components). Registered explicitly in `create_app`'s
model import list per the app-factory convention.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `fiscal_year` | int, not null | e.g. `2025` |
| `branch_id` | FK→branches, not null, indexed | per-branch (branch-scoping rule) |
| `status` | str, not null | `closed` / `reopened` |
| `net_income` | Numeric(15,2), not null | snapshot of profit moved to RE (display/audit) |
| `closing_entry_ids` | Text (JSON) | the JE ids this close posted; Reopen reverses exactly these |
| `closed_at` | DateTime, not null | `ph_now()` |
| `closed_by_id` | FK→users, not null | |
| `reopened_at` | DateTime, nullable | |
| `reopened_by_id` | FK→users, nullable | |

- **Unique constraint** on `(fiscal_year, branch_id)`. Reopening flips `status` to
  `reopened` (the row is retained, not deleted); a subsequent re-close flips it back to
  `closed` and rewrites `closing_entry_ids`/`net_income`.
- **No changes to existing tables.** Closing JEs are tagged with new `entry_type` values
  `'closing'` and `'closing_reversal'`; `JournalEntry.entry_type` is a free-form string,
  so there is **no JournalEntry migration**. Only the one new table + its Alembic migration.
- **Audit trail (required).** Every close and reopen calls `log_audit` —
  module `year_end`, action `close` / `reopen`, `record_id` = the `fiscal_year_closes`
  row id, `record_identifier` = `f'{fiscal_year} / {branch}'`, with `new_values`
  capturing `fiscal_year`, `branch_id`, `net_income`, and the `closing_entry_ids`
  (and, for reopen, the reversal JE ids). One audit row per branch per action, so a
  multi-branch close writes one entry per branch. The CRUD tests assert the audit row
  exists with the correct action and reference (per the project "verify the audit log in
  CRUD tests" rule). The posted closing JEs are children of that audited event; the
  general-journal itself is the ledger record of the entries.

## Components

- `app/year_end/models.py` — `FiscalYearClose`.
- `app/year_end/service.py` — pure logic: `close_fiscal_year(year, user_id)`,
  `reopen_fiscal_year(year, user_id)`, plus helpers (`eligible_years()`,
  `nominal_account_balances(year, branch_id)`, `_post_closing_entries(...)`,
  `_reverse_closing_entries(...)`). No request/session access here — testable in isolation.
- `app/year_end/views.py` — blueprint: list closed years, preview, close, reopen.
- `app/year_end/templates/year_end/…` — list + preview + custom confirm modal.
- Edits to `app/reports/financial.py` — `generate_balance_sheet` and `generate_cash_flow`.
- `create_app` — register the model and blueprint; add a `MODULE_REGISTRY` key.

## The close operation

`close_fiscal_year(year N, user_id)` — within one transaction, for **each active branch**:

1. **Identify nominal accounts** using the *same* classification the Income Statement
   uses (Revenue/Income + all Expense incl. Cost of Sales + Income Tax Expense), so the
   profit closed exactly equals the profit reported.
2. **Compute each account's posted balance** as of `Dec 31, year N` for that branch
   (posted JE lines only).
3. **Post three balanced closing JEs**, dated `Dec 31, year N`, `entry_type='closing'`,
   `reference='CLOSE-N'`, general-journal voucher numbering (JV-YYYY-MM-####),
   `status='posted'`, `branch_id` = the branch:
   - **JE1 — Close revenue:** Dr each revenue/income account by its (credit) balance;
     Cr `30301` for the total.
   - **JE2 — Close expenses:** Cr each expense account by its (debit) balance;
     Dr `30301` for the total.
   - **JE3 — Close Income Summary to Retained Earnings:** move the net `30301` balance to
     `30201` (Dr `30301` / Cr `30201` if net profit; reversed if net loss).
   - Each JE balances on its own; reuse the JournalEntry `is_balanced` guard.
4. **Tie-out guard:** assert JE3's net amount equals
   `generate_income_statement(Jan 1 … Dec 31, year N, branch_id)['net_income']`.
   If it does not tie, **abort the entire close** (rollback) — no partial state.
5. **Record** the `fiscal_year_closes` row (`net_income`, the 3 JE ids in `closing_entry_ids`).
6. **Lock periods:** mark all `AccountingPeriod`s within year N closed so nothing can be
   back-posted into the closed year.

Atomicity: if any branch fails, the whole close rolls back (all-or-nothing per invocation).

## Reopen

`reopen_fiscal_year(year N, user_id)`:
- **Guard:** only the *latest* closed year may be reopened (no gaps), keeping RE consistent.
- For each branch's recorded close, post mirror reversing JEs (`entry_type='closing_reversal'`,
  swapped debits/credits, referencing the originals), dated `Dec 31, year N`.
- Unlock year N's `AccountingPeriod`s.
- Set `fiscal_year_closes.status='reopened'`, stamp `reopened_at`/`reopened_by_id`.
- After reopen the year is editable and can be re-closed (which rewrites the close row).

## Guards & access

- **Accountant/admin only**, fully audited. No separate change-request approval — it is a
  posting action like a journal voucher.
- **Sequential close:** year N cannot be closed unless year N-1 is already closed (or N is
  the earliest year that has any posted data).
- **Year must have ended:** close allowed only on/after `Dec 31, year N`.
- **No double close:** enforced by the `(fiscal_year, branch_id)` unique constraint + a
  status check.
- **Drafts block the close:** if any draft/unposted documents exist within year N, the
  close is refused with a message listing them (clean books before closing).

## Reports reconciliation

### Balance Sheet (`generate_balance_sheet`)
- **Retained Earnings line** = the **posted ledger balance of `30201`** as of the report
  date (branch-filtered).
- **`30301 Current-Year Earnings`** shown only if its posted balance is nonzero (≈0 after a
  complete close).
- **Net Income (current year) line** = `generate_income_statement(open_start … as_of_date,
  branch_id)['net_income']`, where `open_start` = the day after the latest closed
  fiscal-year-end for that branch, or `date(1900,1,1)` (inception) if no year is closed.
- Replaces the current "compute prior from inception + current-year net income" block.
- **Backward compatible:** before any close, posted RE = 0 and the open span is
  inception→date, reproducing today's output exactly.

### Cash Flow (`generate_cash_flow`)
- **Exclude** `entry_type IN ('closing','closing_reversal')` from the non-cash movement
  reorganization, so closing entries never get bucketed into Financing. This removes the
  documented closing-entries caveat at `financial.py:381-384`.
- `net_income` for the Operating section continues to use the computed P&L for the report
  range; closing entries (dated year-end) are excluded by the tag regardless of range.

### Trial Balance / General Ledger
- Unchanged. Closing entries are real posted JEs and appear normally; a closed year's Trial
  Balance correctly shows nominal accounts at 0 with RE populated.

## UI

- New **Year-End Close** page (accountant/admin; own `MODULE_REGISTRY` key, configurable in
  user maintenance like other ledger features):
  - **Select an eligible year** → **preview**: the net income to be closed and the exact JEs
    that will post (per branch).
  - **Confirm** via a custom HTML modal containing `{{ csrf_token() }}` (no JS popups).
  - Action buttons **"Close Year"** / **"Reopen Year"** (action verbs — not document Save).
  - **List** of closed years with status, net income, closed-by, dates, and a Reopen action
    (custom modal confirm) on the latest closed year.
- Peso amounts use the literal `₱` glyph; design tokens only; responsive.

## Testing (TDD)

Service-level (isolated):
- Close posts three balanced JEs that zero every nominal account; profit-to-RE equals
  `generate_income_statement(year)['net_income']`; `fiscal_year_closes` row recorded with
  the JE ids; year's periods locked; audit row written.
- **Net-loss year** closes correctly (RE decreases; JE3 reversed direction).
- Tie-out guard aborts (rolls back) if profit doesn't reconcile.
- Reopen reverses exactly (mirror JEs), unlocks periods, flips status; re-close works.

Reports:
- Balance Sheet after close: RE line == posted `30201`; nominal accounts gone; BS balances;
  branch-filtered BS balances.
- **Balance Sheet pre-close unchanged** (regression vs today's computed output).
- Cash Flow excludes closing entries (Financing not polluted) and still reconciles.

Guards/access:
- Sequential close enforced; double-close blocked; accountant/admin only; drafts block close.

## Out of scope

- Dividends/withdrawals closing (no such accounts in use).
- Monthly/period closing changes (locking already exists, unchanged).
- Automatic scheduling of the close (manual action only).

## Risks / notes

- The `'closing'` entry-type tag is load-bearing for Cash Flow correctness — it must be set
  on every closing JE and honored by `generate_cash_flow`.
- `30301` and `30201` are assumed present (they exist in `cas_demo.db`). The service must
  raise a clear error if either is missing in the COA (mirror the existing
  "account not found in COA" pattern).
- Income Tax Expense is a normal expense account and closes like any other → net income to
  RE is after-tax, consistent with the Income Statement.
