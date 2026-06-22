# Cash Flow Statement — Direct Method — Design

**Date:** 2026-06-22
**Status:** Approved (design); implementation pending
**Author:** Claude + owner
**Builds on:** `docs/superpowers/specs/2026-06-22-cash-flow-statement-indirect-design.md` (indirect method, shipped + pushed)

## Goal

Add the **direct method** to the existing Statement of Cash Flows, exposed as a
method toggle on the same `/reports/cash-flow` page. The direct method presents
actual operating cash receipts and payments grouped into standard PFRS lines,
plus a PAS 7 reconciliation of net income to operating cash flow. Investing and
Financing sections are reused verbatim from the indirect method.

This completes the owner's "we will do both Direct and Indirect" intent. The
indirect path is already live; this spec adds the direct path **without changing
the indirect output**.

## Decisions (locked)

1. **UI:** one page, `/reports/cash-flow?method=indirect|direct` (default
   `indirect`). One nav item, one `cash_flow` module-access key (unchanged — the
   method is a query param, not a new endpoint). An **Indirect | Direct** toggle
   at the top of the screen; Excel/Print links carry the selected method.
2. **Operating granularity:** standard PFRS grouping (Cash received from
   customers / Cash paid to suppliers / Cash paid for operating expenses / Taxes
   paid / Other operating), mapped from contra accounts by name + code.
3. **Reconciliation note:** include the PAS 7 reconciliation of net income to
   net operating cash flow as a supplementary schedule below the direct
   statement — it reuses the indirect Operating computation verbatim.

## Core principle — only Operating differs

The indirect/direct distinction affects **only the Operating section**.
Therefore:

- **Investing and Financing are computed identically** to the indirect method
  and reused verbatim (`generate_cash_flow` already produces them).
- The **reconciliation note** *is* the indirect Operating section (net income →
  + depreciation → ± working-capital changes). It is already computed.
- `net_change`, `cash_begin`, `cash_end`, `is_reconciled`, `difference` are
  unchanged — so the direct statement reconciles by exactly the same identity.

**Why direct operating total == indirect operating total (always):** both equal
the real operating cash flow. A credit sale (`Dr AR / Cr Revenue`) touches no
cash → contributes 0 to direct operating *and* nets to 0 in indirect operating
(revenue +X in net income, AR increase −X in working capital). A collection
(`Dr Cash / Cr AR`) is +X in both. Depreciation (`Dr Dep Exp / Cr Accum Depr`)
touches no cash → naturally excluded from direct operating with no add-back
needed, and nets to 0 in indirect (expense −X in NI, +X add-back). The two
operating totals are equal for every transaction shape.

## Direct operating derivation

For every posted JE (in period, branch-filtered) that has **at least one cash
line** (`_is_cash` account), iterate its **non-cash** lines. Each non-cash line's
**cash effect** = `credit − debit` (positive = cash inflow; this is the cash
attributable to that account, since within a balanced JE the cash movement
equals the negative of the non-cash movement).

Classify each non-cash line by its account into an **activity** (same rules as
the indirect bucketing):

- **Operating** — revenue (`4…`), expense (`5…`), current assets ex-cash (`10…`
  non-cash), current liabilities (`20…`).
- **Investing** — non-current asset cost (`11…`) excluding accumulated
  depreciation. *(Reused from indirect; not recomputed here.)*
- **Financing** — non-current liabilities (`21…`) + equity (`30…`). *(Reused.)*

Only **operating** contra lines feed the direct operating section. Within
operating, assign each line to a PFRS sub-line by **first match wins**:

| Order | Sub-line | Match rule (case-insensitive) |
|---|---|---|
| 1 | **Taxes paid** | account name contains `vat`, `withholding`, `wht`, or `income tax` |
| 2 | **Cash received from customers** | revenue (code `4…`) OR name contains `receivable` |
| 3 | **Cash paid to suppliers** | code `501…` (cost of construction/sales) OR name contains `payable`, `inventory`, `construction in progress`, or `materials` |
| 4 | **Cash paid for operating expenses** | any remaining expense (code `5…`) |
| 5 | **Other operating receipts/(payments)** | catch-all — any operating contra not matched above |

Each sub-line sums the cash effects of its matching lines (inflows +, outflows
−). Sub-lines with a zero total are omitted. The five sub-lines are emitted in
the order above. `operating.total` = sum of the sub-line amounts (equals the
indirect operating total; asserted by tests).

**Tie-out guarantee.** Because the sub-line mapping only re-labels *operating*
contras (it never moves a flow between activities, and the catch-all ensures no
operating flow is dropped), the direct operating total is exactly the indirect
operating total, and `net_change = operating + investing + financing` continues
to equal `cash_end − cash_begin`. The reconciliation banner is the runtime
safety net, identical to the indirect path.

Edge cases:
- **Cash-to-cash transfer** (`Dr Cash in Bank / Cr Cash on Hand`): no non-cash
  lines → contributes nothing to any sub-line; net cash movement across the two
  cash accounts is 0. Correctly ignored.
- **JE with mixed operating + investing contras** touching cash: each non-cash
  line is attributed by its own account, so operating and investing each get
  their correct slice.
- **No cash-touching JEs**: all operating sub-lines empty, `operating.total = 0`.

## Generator — `generate_cash_flow(start, end, branch_id, method)`

Extend the existing function in `app/reports/financial.py`. `method='indirect'`
keeps its current return shape **unchanged**. `method='direct'` returns:

```python
{
    'period_start': date, 'period_end': date,
    'method': 'direct',
    'operating': {
        'lines': [ {'name': str, 'amount': float}, ... ],   # PFRS sub-lines, signed, non-zero only
        'total': float,
    },
    'investing': { 'lines': [...], 'total': float },          # identical to indirect
    'financing': { 'lines': [...], 'total': float },          # identical to indirect
    'reconciliation': {                                        # PAS 7 note = indirect operating
        'net_income': float,
        'depreciation': float,
        'working_capital': [ {'name': str, 'amount': float}, ... ],
        'total': float,                                        # == operating.total
    },
    'net_change': float, 'cash_begin': float, 'cash_end': float,
    'is_reconciled': bool, 'difference': float,
}
```

Implementation approach (DRY): refactor the indirect computation so the
operating pieces (`net_income`, `depreciation`, `working_capital`, the operating
total) and the investing/financing/cash-balance pieces are computed once and
reused by both methods. For `direct`, compute the operating sub-lines via the
contra-attribution pass over cash-touching JEs, and place the indirect operating
result under `reconciliation`. Reuse the existing `_is_cash`,
`_is_depreciation_name`, `movement`, and `cash_balance` helpers. Add a module-level
`_direct_operating_subline(account)` returning the sub-line label for an
operating contra (the table above), or `None` if the account is not operating.

`method` not in (`'indirect'`, `'direct'`) → `ValueError` (tighten the existing
guard).

## Export — `statement_export.py`

- `cash_flow_lines(cf)` branches on `cf['method']`:
  - `indirect` → current output (unchanged).
  - `direct` → operating header + sub-line rows + "Net cash … operating
    activities" subtotal (`top_bottom`); then the **shared** investing/financing
    sections + NET INCREASE/(DECREASE) IN CASH + begin/end cash (identical
    helper code, factored out); then a **reconciliation note** block:
    a `subheader` "Reconciliation of net income to net cash from operating
    activities", `Net Income (period)`, optional `Add: Depreciation`, the
    working-capital lines, and a `subtotal` "Net cash from operating activities"
    (`top_bottom`) carrying `reconciliation.total`.
- `build_cash_flow_xlsx(cf, period_label, company, branch_name, filename)`
  branches on `cf['method']` the same way, with live `=SUM` formulas for the
  direct operating subtotal (over its sub-line rows) and for the reconciliation
  subtotal (over its detail rows). Investing/financing/net-change/cash-end
  formulas are unchanged. The sheet title stays `Cash Flow`; the method label
  ("Indirect Method" / "Direct Method") appears under the statement title.

Factor the shared investing/financing/net-change/begin/end emission (lines and
xlsx rows) into a small internal helper so the two method branches do not
duplicate it.

## Views — `app/reports/views.py`

- Add a `_cf_method()` helper: `request.args.get('method', 'indirect')`,
  validated to `{'indirect','direct'}` (fallback `indirect`).
- `cash_flow`, `cash_flow_export_excel`, `cash_flow_print` read the method and
  pass it to `generate_cash_flow(...)`. The export `period_label` and `filename`
  gain the method (e.g. `Cash_Flow_Direct_2026-01-01_to_2026-06-30.xlsx`).
- No new endpoints, **no new module-access key** (the existing `cash_flow` key
  already gates all three; the method is a query param).

## Templates

- `reports/cash_flow.html`:
  - An **Indirect | Direct** toggle (two links to the same page with
    `method=indirect` / `method=direct`, preserving `start_date`/`end_date`; the
    active method styled as selected — design tokens, no JS popups).
  - The card sub-title shows "Indirect Method" / "Direct Method".
  - Render branches on `cash_flow.method`: indirect = current layout; direct =
    operating sub-lines + subtotal, then the shared investing/financing/net/begin/
    end rows, then the reconciliation note table.
  - Excel/Print buttons append the current `method`.
  - Reconciliation banner unchanged. Negatives in parentheses; literal `₱`.
- `reports/cash_flow_print.html`:
  - Title shows the method label.
  - Render from `lines` (already method-aware via `cash_flow_lines`), so the
    print template needs only to ensure the `subheader` kind (reconciliation
    note header) is styled — it already is.

## Files

- **Modify** `app/reports/financial.py` — refactor `generate_cash_flow` for both
  methods; add `_direct_operating_subline(account)`.
- **Modify** `app/reports/statement_export.py` — method branches in
  `cash_flow_lines` + `build_cash_flow_xlsx`; factor shared investing/financing
  emission.
- **Modify** `app/reports/views.py` — `_cf_method()` + pass-through in 3 routes.
- **Modify** `app/reports/templates/reports/cash_flow.html` — toggle + direct
  render + reconciliation note.
- **Modify** `app/reports/templates/reports/cash_flow_print.html` — method label
  (and confirm `subheader` styling).
- **Modify** `tests/unit/test_cash_flow_generator.py` — add direct-method tests.
- **Modify** `tests/unit/test_cash_flow_export.py` — add direct `cash_flow_lines`
  tests.
- **Modify** `tests/integration/test_cash_flow_views.py` — add direct render +
  toggle + excel/print(method=direct) tests.

## Testing (TDD)

**Unit — generator (`test_cash_flow_generator.py`):** reuse the existing
`_build` fixture (it already has cash, AR, equipment, accum-depr, AP, capital,
revenue, depreciation, salaries).
1. **Direct reconciles**: `method='direct'` → `net_change == cash_end −
   cash_begin`; `is_reconciled True`.
2. **Direct operating total == indirect operating total**: call both, assert
   `direct['operating']['total'] == indirect['operating']['total']`.
3. **Sub-line classification**: the collection-style flows land in "Cash received
   from customers"; AP-paying flows in "Cash paid to suppliers"; assert the
   expected sub-line names appear with the right signs. (Augment `_build` with a
   cash collection `Dr Cash / Cr AR` and a cash payment `Dr AP / Cr Cash` so the
   sub-lines are non-trivial.)
4. **Reconciliation note**: `reconciliation.total == operating.total`;
   `reconciliation.net_income` equals the IS net income; depreciation present.
5. **Investing/financing reused**: `direct['investing'] == indirect['investing']`
   and same for financing.
6. **Guard**: `method='cash'` (or any other) → `ValueError`; `method='indirect'`
   return shape is byte-for-byte unchanged from today (regression guard — assert
   the indirect dict still has its original keys and no `reconciliation`).

**Unit — export (`test_cash_flow_export.py`):** `cash_flow_lines(direct_cf)`
emits the operating sub-lines, the shared investing/financing/net/begin/end
lines, and a reconciliation note block (a `subheader` + detail + subtotal); the
indirect call is unchanged.

**Integration (`test_cash_flow_views.py`):**
1. `/reports/cash-flow?method=direct` renders 200 with `Direct Method`, the
   operating sub-line headers, and `Reconciliation of net income`.
2. The page shows both toggle links (indirect + direct).
3. `/reports/cash-flow/export/excel?method=direct` → 200 + spreadsheet content
   type; filename contains `Direct`.
4. `/reports/cash-flow/print?method=direct` → 200 + `Direct Method`.
5. Default (no `method`) still renders the indirect statement (regression).

Read-only report: no audit-log assertions (consistent with the other statements).

## Out of scope

- Interest-paid as its own operating line (folds into operating expenses /
  financial unless requested later).
- Comparative prior-period columns.
- Configurable contra→sub-line mapping (the rules are code constants;
  misclassification only re-labels within Operating, never breaks the totals).
- The latent indirect-method reconciliation guard (uncovered-account → red
  banner test) tracked separately in the open backlog — not part of this spec.
