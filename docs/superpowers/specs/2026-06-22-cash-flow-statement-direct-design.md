# Cash Flow Statement — Direct Method — Design

**Date:** 2026-06-22
**Status:** Approved (design); implementation pending
**Author:** Claude + owner
**Builds on:** `docs/superpowers/specs/2026-06-22-cash-flow-statement-indirect-design.md` (indirect method, shipped + pushed)

## Goal

Add the **direct method** to the existing Statement of Cash Flows, exposed as a
method toggle on the same `/reports/cash-flow` page. The direct method presents
**actual operating cash receipts and payments** grouped into standard PFRS
lines, the investing/financing cash flows, a **non-cash transactions disclosure
note**, and a PAS 7 reconciliation of net income to operating cash flow. The
already-shipped indirect statement is **left unchanged**.

This completes the owner's "we will do both Direct and Indirect" intent.

## Decisions (locked)

1. **UI:** one page, `/reports/cash-flow?method=indirect|direct` (default
   `indirect`). One nav item, one `cash_flow` module-access key (unchanged — the
   method is a query param, not a new endpoint). An **Indirect | Direct** toggle
   at the top of the screen; Excel/Print links carry the selected method.
2. **Operating granularity:** standard PFRS grouping (Cash received from
   customers / Cash paid to suppliers / Cash paid for operating expenses / Taxes
   paid / Other operating).
3. **Reconciliation note:** include the PAS 7 reconciliation of net income to
   operating cash flow as a supplementary schedule — it reuses the indirect
   Operating computation.
4. **Non-cash transactions (owner decision 2026-06-22):** the direct method
   shows **only real cash**. Non-cash transactions (e.g. `cas_demo.db` JE3:
   `Dr Construction Equipment ₱2,000,000 / Cr Capital Stock ₱2,000,000`) are
   **excluded** from the three sections and listed in a **disclosure note**. The
   shipped indirect statement is **not** modified (it still shows such entries in
   investing/financing — the two methods will differ there; expected).

## Core principle — direct method decomposes ACTUAL cash

The direct method decomposes the cash that actually moved in the period into the
three activities, so **all three sections are computed from cash-touching
journal entries** — not reused from the indirect method.

**Ties by construction.** For every posted JE that has at least one cash line,
the cash lines' `Σ(debit − credit)` equals the negative of the non-cash lines'
(the JE balances). Summed over all cash-touching JEs, the total cash movement
equals `Σ(credit − debit)` over their non-cash lines. The direct sections ARE
that decomposition, so `net_change = operating + investing + financing =
cash_end − cash_begin` identically. A non-cash transaction (no cash line) is
never counted — it is disclosed in the note instead. The reconciliation banner
stays as a runtime safety net (always green for direct).

## Direct derivation — decompose cash by contra activity

For every posted JE (in period, branch-filtered) with **at least one cash line**
(`_is_cash` account), aggregate the **cash effect** of each non-cash line **per
non-cash account**, where cash effect = `Σ(credit) − Σ(debit)` (positive = cash
inflow). Classify each non-cash account into an activity via `_direct_activity`:

- **Investing** — non-current asset cost (`11…`) excluding accumulated
  depreciation (name contains "depreciation").
- **Financing** — non-current liabilities (`21…`) + equity (`30…`).
- **Operating** — everything else (revenue `4…`, expense `5…`, current assets
  ex-cash `10…`, current liabilities `20…`, plus any stray account). The
  catch-all guarantees nothing is dropped, so the three sections always sum to
  the cash movement.

**Investing** and **Financing** are emitted as **per-account lines** (non-zero
cash effect only): `"(Acquisition)/disposal of <name>"` and `"<name>"`. In
`cas_demo.db` both are empty for the direct method (the only equipment/capital
activity is the non-cash JE3, excluded) — correct.

**Operating** accounts are grouped into PFRS sub-lines by `_direct_operating_subline`,
**first match wins** (case-insensitive on name; `code` is the account code):

| Order | Sub-line | Match rule |
|---|---|---|
| 1 | **Taxes paid** | name contains `vat`, `withholding`, `wht`, or `income tax` |
| 2 | **Cash received from customers** | code starts `4` OR name contains `receivable` |
| 3 | **Cash paid to suppliers** | code starts `501` OR name contains `payable`, `inventory`, `construction in progress`, or `materials` |
| 4 | **Cash paid for operating expenses** | code starts `5` (remaining expenses) |
| 5 | **Other operating receipts/(payments)** | catch-all |

Each sub-line sums the cash effects of its accounts (inflows +, outflows −);
zero-total sub-lines are omitted; the five are emitted in the order above.
`operating.total`, `investing.total`, `financing.total` are the sums of their
lines; `net_change = operating.total + investing.total + financing.total`.

## Non-cash transactions disclosure note

A separate list (PAS 7 supplemental disclosure). Identify posted in-period
branch JEs that (a) do **not** touch a cash account, and (b) touch at least one
**investing** account (`11…` excluding accumulated depreciation) **or financing**
account (`21…`/`30…`). Depreciation entries are excluded automatically because
their only `11…` account is accumulated depreciation (rule b requires a
non-accum-depr investing or a financing account). For each such JE emit
`{'description': je.description or je.reference, 'amount': float(total_debit)}`.
In `cas_demo.db` this yields one entry: JE3, ₱2,000,000.

## Reconciliation note (net income → operating cash)

Reuse the indirect Operating computation verbatim as a supplementary schedule:
`net_income`, `+ depreciation`, the working-capital change lines, and the
"Net cash from operating activities" subtotal. This equals the direct operating
cash total when no non-cash transaction mixes an operating account with an
investing/financing account (true for `cas_demo.db` — JE3 involves only
investing + financing accounts, no operating account). **Documented limitation:**
if a future non-cash entry pairs an operating account with an investing/financing
account (e.g. equipment bought on credit, `Dr Equipment / Cr AP`), the indirect
operating figure can diverge from direct operating cash; the reconciliation note
is the indirect-basis figure and would then not foot exactly to the direct
operating subtotal. Acceptable per the owner's "actual cash only" decision; noted
in a code comment.

## Generator — `generate_cash_flow(start, end, branch_id, method)`

Extend the existing function in `app/reports/financial.py`. `method='indirect'`
keeps its current return shape **unchanged** (regression-guarded by a test).
`method='direct'` returns:

```python
{
    'period_start': date, 'period_end': date,
    'method': 'direct',
    'operating': { 'lines': [ {'name': str, 'amount': float}, ... ], 'total': float },
    'investing': { 'lines': [ {'name': str, 'amount': float}, ... ], 'total': float },
    'financing': { 'lines': [ {'name': str, 'amount': float}, ... ], 'total': float },
    'noncash':   [ {'description': str, 'amount': float}, ... ],           # may be empty
    'reconciliation': {                                                    # indirect operating
        'net_income': float, 'depreciation': float,
        'working_capital': [ {'name': str, 'amount': float}, ... ],
        'total': float,
    },
    'net_change': float, 'cash_begin': float, 'cash_end': float,
    'is_reconciled': bool, 'difference': float,
}
```

Implementation: keep the existing indirect computation; capture its result dict
in a local `indirect` and `return indirect` when `method == 'indirect'`
(byte-for-byte unchanged). For `method == 'direct'`, run the cash-decomposition
pass (below) for the three sections + the non-cash note, set `reconciliation =
indirect['operating']`, and compute `net_change` from the direct section totals.
Reuse the existing `_is_cash`, `_is_depreciation_name`, `cash_balance` helpers.
Add module-level `_direct_activity(account)` and `_direct_operating_subline(account)`
helpers and the sub-line order constant. Tighten the guard to
`if method not in ('indirect', 'direct'): raise ValueError(...)`.

Cash-decomposition query: find posted in-period branch JE ids whose lines hit a
cash account; then sum `credit − debit` grouped by account over the non-cash
lines of those JEs; bucket per `_direct_activity`. Empty cash-account set → all
sections empty.

## Export — `statement_export.py`

- `cash_flow_lines(cf)` branches on `cf['method']`:
  - `indirect` → current output (unchanged).
  - `direct` → operating header + sub-line rows + "Net cash … operating
    activities" subtotal (`top_bottom`); investing header + per-account lines +
    subtotal; financing header + per-account lines + subtotal; NET
    INCREASE/(DECREASE) IN CASH (`double_bottom`); Cash at beginning; Cash at end
    (`double_bottom`); then, if `cf['noncash']`, a `subheader` "Non-cash investing
    and financing transactions" + one `account` line per note entry; then a
    `subheader` "Reconciliation of net income to net cash from operating
    activities" + `Net Income (period)` + optional `Add: Depreciation` + the
    working-capital lines + a `subtotal` "Net cash from operating activities"
    (`top_bottom`).
- `build_cash_flow_xlsx(cf, period_label, company, branch_name, filename)`
  branches the same way, with live `=SUM` formulas for each section subtotal
  (over its line rows, or `0` when empty), `net_change =
  operating+investing+financing` row refs, `cash_end = net_change + cash_begin`,
  and a `=SUM` for the reconciliation subtotal. Method label under the title
  reads "Indirect Method" / "Direct Method"; sheet title stays `Cash Flow`.

Factor the shared section-emission (header + lines + subtotal) so the two method
branches do not duplicate row/line code.

## Views — `app/reports/views.py`

- Add `_cf_method()`: `request.args.get('method', 'indirect')`, validated to
  `{'indirect','direct'}` (fallback `indirect`).
- `cash_flow`, `cash_flow_export_excel`, `cash_flow_print` read the method, pass
  it to `generate_cash_flow(...)`, and forward it to the template / filename. The
  export `filename` gains the method (e.g.
  `Cash_Flow_Direct_2026-01-01_to_2026-06-30.xlsx`).
- No new endpoints, **no new module-access key**.

## Templates

- `reports/cash_flow.html`:
  - An **Indirect | Direct** toggle (two links to the same page with
    `method=indirect`/`method=direct`, preserving `start_date`/`end_date`; active
    method styled selected — design tokens, no JS popups).
  - Card sub-title shows "Indirect Method" / "Direct Method".
  - Render branches on `cash_flow.method`: indirect = current layout; direct =
    operating sub-lines + subtotal, investing per-account lines + subtotal,
    financing per-account lines + subtotal, NET INCREASE, begin/end cash, then
    the non-cash note table (if any) and the reconciliation note table.
  - Excel/Print buttons append the current `method`. Reconciliation banner
    unchanged. Negatives in parentheses; literal `₱`.
- `reports/cash_flow_print.html`:
  - Title shows the method label.
  - Renders from `lines` (already method-aware via `cash_flow_lines`), so it
    needs only the `subheader` kind styled (already is).

## Files

- **Modify** `app/reports/financial.py` — `method='direct'` branch in
  `generate_cash_flow`; `_direct_activity`, `_direct_operating_subline`, sub-line
  order constant; cash-decomposition + non-cash note.
- **Modify** `app/reports/statement_export.py` — method branches in
  `cash_flow_lines` + `build_cash_flow_xlsx`; factor shared section emission.
- **Modify** `app/reports/views.py` — `_cf_method()` + pass-through in 3 routes.
- **Modify** `app/reports/templates/reports/cash_flow.html` — toggle + direct
  render + non-cash note + reconciliation note.
- **Modify** `app/reports/templates/reports/cash_flow_print.html` — method label.
- **Modify** `tests/unit/test_cash_flow_generator.py` — direct-method tests.
- **Modify** `tests/unit/test_cash_flow_export.py` — direct `cash_flow_lines` tests.
- **Modify** `tests/integration/test_cash_flow_views.py` — direct render + toggle
  + excel/print(method=direct) tests.

## Testing (TDD)

**Unit — generator (`test_cash_flow_generator.py`):** extend the `_build`
fixture with a non-cash investing+financing JE (`Dr Equipment / Cr Capital`, no
cash) and cash collection/payment JEs so the sections are non-trivial.
1. **Direct reconciles**: `method='direct'` → `net_change == cash_end −
   cash_begin`; `is_reconciled True`.
2. **Direct sections = cash only**: the non-cash equipment/capital JE does NOT
   appear in `investing`/`financing` lines; it DOES appear in `noncash` with the
   right amount.
3. **Operating sub-lines**: a cash collection (`Dr Cash / Cr AR`) lands in "Cash
   received from customers" (positive); a cash payment of AP (`Dr AP / Cr Cash`)
   in "Cash paid to suppliers" (negative).
4. **Reconciliation note**: `reconciliation.net_income` equals the IS net income;
   depreciation present; for this fixture `reconciliation.total ==
   operating.total`.
5. **Guard + indirect unchanged**: `method='xyz'` → `ValueError`;
   `method='indirect'` returns the original keys with **no** `noncash`/`reconciliation`
   keys (regression guard).

**Unit — export (`test_cash_flow_export.py`):** `cash_flow_lines(direct_cf)`
emits operating sub-lines, investing/financing sections, NET INCREASE +
begin/end, a non-cash note block (when `noncash` non-empty), and a reconciliation
note block; the indirect call output is unchanged.

**Integration (`test_cash_flow_views.py`):**
1. `/reports/cash-flow?method=direct` → 200 with `Direct Method`, the operating
   sub-line headers, `Non-cash`, and `Reconciliation of net income`.
2. Both toggle links (indirect + direct) present.
3. `/reports/cash-flow/export/excel?method=direct` → 200 + spreadsheet type;
   filename contains `Direct`.
4. `/reports/cash-flow/print?method=direct` → 200 + `Direct Method`.
5. Default (no `method`) still renders the indirect statement (regression).

Read-only report: no audit-log assertions.

## Out of scope

- Interest-paid as its own operating line.
- Comparative prior-period columns.
- Modifying the shipped indirect statement's non-cash handling (owner chose to
  leave it).
- Tracing AP/AR settlements back to their original purpose (the direct method
  classifies by the immediate contra account — AP payment = operating).
- The latent indirect-method reconciliation guard (tracked separately in the
  open backlog).
