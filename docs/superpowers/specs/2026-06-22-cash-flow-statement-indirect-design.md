# Cash Flow Statement (Indirect Method) — Design

**Date:** 2026-06-22
**Status:** Approved (design); implementation pending
**Author:** Claude + owner

## Goal

Activate the **Cash Flow** report (currently a bare nav placeholder pointing at
`dashboard.under_development`) as a proper **Statement of Cash Flows, indirect
method**, classifying the period's cash movement into Operating / Investing /
Financing activities and reconciling to the actual change in cash. This is the
last of the four core financial statements (TB, IS, BS already activated).

**Scope note — Direct method deferred.** The owner wants *both* indirect and
direct methods eventually. This spec builds **indirect only**. The view and
generator are structured so a `method` parameter (`'indirect'` | `'direct'`)
and a UI toggle can be added later without reworking the existing path — but no
direct-method code is written now (YAGNI).

## Background — what already exists

- `app/reports/financial.py` has `generate_trial_balance`, `generate_income_statement`,
  `generate_balance_sheet`, `generate_general_ledger`. The IS returns `net_income`
  for a period; the BS reuses a `leaves(group)` hierarchy walker and a
  `balance(account_id, credit_positive)` as-of helper.
- `app/reports/statement_export.py` builds professional `.xlsx` (live formulas,
  accounting number format `#,##0.00;(#,##0.00)`, borders, gridlines off, branch
  hidden when a single branch) for IS and BS.
- `app/reports/views.py` exposes view + `export/excel` + `print` routes per
  statement; **no CSV** for financial statements.
- `app/users/module_access.py` `MODULE_REGISTRY` gates each report by a key
  (staff need an explicit grant; admin/accountant/viewer always allowed). Keys
  `trial_balance`, `income_statement`, `balance_sheet` already exist under
  section `'Ledger'`.
- Cash accounts in the COA: `10101 Cash on Hand`, `10102 Petty Cash Fund`,
  `10111 Cash in Bank - Current Account`, `10112 Cash in Bank - Savings Account`
  — all current assets whose **name contains "cash"** (case-insensitive). This
  is the cash-account selector.

## Method — indirect, derived from per-account period movement

A period report (start → end, like the Income Statement; default year-to-date).

For every active account, compute its **net movement during the period** in
debit-positive terms: `Δ = Σ(debit) − Σ(credit)` for posted lines with
`start ≤ entry_date ≤ end` (branch-filtered). Because every journal entry
balances, `Σ Δ over ALL accounts = 0`, therefore:

```
Δcash = −Σ( Δ of every non-cash account )
```

The cash flow statement reorganizes those non-cash movements into the three
activity buckets. Bucketing by COA classification:

| Bucket | Accounts | CF contribution |
|---|---|---|
| Operating | revenue (`4…`), expense (`5…`), current assets ex-cash (`10…` non-cash), current liabilities (`20…`) | `−Σ Δ` of these, **plus** the depreciation add-back (below) |
| Investing | non-current asset **cost** accounts (`11…`) **excluding** Accumulated Depreciation | `−Σ Δ` of these |
| Financing | non-current liabilities (`21…`) + equity (`30…`) | `−Σ Δ` of these |

### Depreciation — the one special case

Depreciation is a non-cash expense. Standard indirect presentation **adds it
back** in Operating, and shows only **gross** asset purchases in Investing.

- **Add-back** = period amount of **depreciation EXPENSE** accounts — expense
  accounts (`account_type == 'Expense'` or code `5…`) whose name contains
  `"depreciation"` (case-insensitive). Amount = `Σ(debit) − Σ(credit)` over the
  period (a positive add-back).
- **Accumulated Depreciation** (a contra-asset inside `11…`, identified by name
  containing `"depreciation"`) is **excluded** from the Investing bucket, so
  Investing reflects only real cash asset purchases.

**Why it still ties:** excluding Accumulated Depreciation from Investing drops
`−Δ(accum.depr.) = +depreciation` from the total; the operating add-back
(`+depreciation`) restores exactly that amount. Depreciation expense (Dr) equals
the Accumulated Depreciation credit on the same entries, so the two are equal
and opposite. Net effect on the grand total: zero → the statement still ties to
`Δcash`. Presentation is correct: Operating shows `+depreciation`, Investing
shows only gross purchases.

### Reconciliation

- `net_change` = operating + investing + financing.
- `cash_begin` = Σ over cash accounts of `balance(account_id, credit_positive=False)`
  as of `start − 1 day`.
- `cash_end` = Σ over cash accounts as of `end`.
- `is_reconciled` = `abs(net_change − (cash_end − cash_begin)) < 0.01`.

A banner shows ✓ Reconciled when net change equals ending − beginning cash (it
always should; the banner surfaces any classification gap), mirroring the
Balance Sheet's balanced banner.

### Net-income presentation in Operating

Rather than printing `−Σ Δ(revenue, expense)` as one opaque number, Operating is
presented in the conventional indirect layout:

```
Net Income (period)                          ← generate_income_statement(start,end)['net_income']
Add: Depreciation                            ← depreciation add-back (omit line if zero)
Changes in operating assets and liabilities:
  (Increase)/decrease in <each current asset ex-cash with non-zero Δ>   ← −Δ(asset)
  Increase/(decrease) in <each current liability with non-zero Δ>       ← −Δ(liability)
Net cash provided by/(used in) operating activities
```

`net_income + depreciation_addback + Σ(working-capital lines)` equals
`−Σ Δ(revenue, expense, current-assets-ex-cash, current-liabilities) + addback`,
which is the Operating bucket total. (Net income `= −Σ Δ(revenue, expense)`; the
working-capital lines `= −Σ Δ(current assets ex-cash, current liabilities)`.)

Investing and Financing are presented per-account (non-zero Δ only):
`(Acquisition)/disposal of <account>` and `<account>` respectively, each
`−Δ(account)`.

## Generator — `generate_cash_flow(start_date, end_date, branch_id=None, method='indirect')`

Lives in `app/reports/financial.py`. `method` defaults to `'indirect'`; any
other value raises `ValueError` for now (forward-compatible signature for the
future direct method). Reuses the BS-style `leaves`, branch filter, and an
as-of `balance(account_id, credit_positive)` helper for begin/end cash; adds a
`movement(account_id)` helper returning debit-positive period Δ as `Decimal`.

Classification helpers (module-level, by code prefix + name):

```python
def _is_cash(account):
    return 'cash' in (account.name or '').lower()

def _is_depreciation_name(account):
    return 'depreciation' in (account.name or '').lower()
```

Returns floats for template/export consumption:

```python
{
    'period_start': date, 'period_end': date,
    'method': 'indirect',
    'operating': {
        'net_income': float,
        'depreciation': float,                 # add-back; 0.0 if none
        'working_capital': [ {'name': str, 'amount': float}, ... ],  # signed cash effect
        'total': float,
    },
    'investing': { 'lines': [ {'name': str, 'amount': float}, ... ], 'total': float },
    'financing': { 'lines': [ {'name': str, 'amount': float}, ... ], 'total': float },
    'net_change': float,
    'cash_begin': float,
    'cash_end': float,
    'is_reconciled': bool,
    'difference': float,                        # abs(net_change − (cash_end − cash_begin))
}
```

Sign conventions in `working_capital` / `investing` / `financing` line amounts:
all are the **cash effect** (`−Δ` in debit-positive terms), so a cash *outflow*
is negative and an *inflow* is positive — the template/Excel render negatives in
parentheses via the accounting format. Lines with a zero cash effect are omitted.

Edge cases:
- No cash accounts found → `cash_begin = cash_end = 0`; statement still computes
  (net_change should be 0).
- Revenue with zero net income and no movements → all totals 0, reconciled True.
- **Closing-entries caveat** (documented in a code comment, same as the BS): if
  year-end closing entries are ever posted to a real Retained Earnings equity
  account, that movement lands in Financing and double-counts net income. Not an
  issue on the current books (no closing entries).

## Presentation / activation recipe (matches TB, IS, BS)

- **View** `cash_flow` in `app/reports/views.py`: `@login_required`, gated by the
  new `cash_flow` MODULE_REGISTRY key, YTD default date range via a shared
  `_is_params()`-style helper (reuse the IS date-range param helper), renders
  `reports/cash_flow.html`. Branch scoping via `session['selected_branch_id']`.
- **Excel** `cash_flow/export/excel`: `build_cash_flow_xlsx(...)` in
  `statement_export.py` — live `=SUM` formulas for each section total, a
  `net_change` formula `=operating+investing+financing`, accounting number
  format, borders (single rule under each section total, double rule under
  NET INCREASE/(DECREASE) IN CASH and under Cash at end), gridlines off, branch
  hidden when a single branch, company header.
- **Print** `cash_flow/print`: `reports/cash_flow_print.html` with the BIR
  company header (reuse the `_bs_company_branch`-style helper).
- **No CSV.**
- **Module access**: add a `cash_flow` key (section `'Ledger'`) gating the view +
  `export/excel` + `print` endpoints (no csv).
- **Nav**: swap the `nav-item--soon` Cash Flow link in `base.html` for a real
  `can_access_module`-gated link with a `startswith`-style active check (bump any
  shared static `?v=N` only if a static asset changes).
- **Reports index card**: add a Cash Flow card to `reports/index.html`.
- **Design tokens** only; literal `₱`.

### Screen layout

Shown **fully expanded** (no collapsible groups — these are computed statement
lines, not account groups to drill into). Three activity sections with their
line items and a "Net cash …" subtotal each, then NET INCREASE/(DECREASE) IN
CASH, Cash at beginning, Cash at end, and the reconciliation banner. A
"Change Date" modal sets the period (start + end), like the IS.

## Files

- **Modify** `app/reports/financial.py` — add `generate_cash_flow` + `_is_cash`,
  `_is_depreciation_name` helpers.
- **Modify** `app/reports/statement_export.py` — add `cash_flow_lines(cf)` and
  `build_cash_flow_xlsx(cf, period_label, company, branch_name, filename)`.
- **Modify** `app/reports/views.py` — un-stub `cash_flow`; add `cash_flow` excel +
  print routes.
- **Modify** `app/users/module_access.py` — add `cash_flow` key (view + excel + print).
- **Create** `app/reports/templates/reports/cash_flow.html`.
- **Create** `app/reports/templates/reports/cash_flow_print.html`.
- **Modify** `app/templates/base.html` — nav swap.
- **Modify** `app/reports/templates/reports/index.html` — add card.
- **Create** `tests/unit/test_cash_flow_generator.py`.
- **Create** `tests/integration/test_cash_flow_views.py`.

## Testing (TDD)

**Unit (`tests/unit/test_cash_flow_generator.py`)** — build a small COA + JEs:
1. **Reconciles**: net_change == cash_end − cash_begin; is_reconciled True.
2. **Operating**: net income line equals IS net income; an AR increase appears as
   a negative working-capital cash effect; an AP increase appears as positive.
3. **Depreciation add-back**: a Dr Depreciation Expense / Cr Accumulated
   Depreciation entry → `operating.depreciation` positive, Accumulated
   Depreciation absent from `investing.lines`, statement still reconciles.
4. **Investing**: an equipment purchase (Dr Equipment / Cr Cash) → investing line
   negative (cash outflow) equal to the purchase.
5. **Financing**: a capital contribution (Dr Cash / Cr Capital Stock) → financing
   line positive.
6. **Empty / no-cash**: no cash accounts → cash_begin/end 0, totals 0, reconciled.

**Integration (`tests/integration/test_cash_flow_views.py`)** — mirror the BS view
tests:
1. requires login (302/401);
2. admin renders 200 with `CASH FLOWS FROM OPERATING ACTIVITIES`,
   `INVESTING`, `FINANCING`, `NET INCREASE`, and `Reconciled`;
3. staff without grant → 302; staff with grant → 200; viewer → 200;
4. excel export 200 + `spreadsheetml` content-type;
5. print renders 200 with company name + `Cash Flow`.

Verify the **audit log is not required** here (read-only report, no writes —
consistent with the other statement views).

## Out of scope

- Direct method (planned next; signature reserved via `method=`).
- Per-account drill-down / collapsible groups.
- Comparative (prior-period) columns.
- Closing-entries / Retained Earnings posting (a separate future feature).
