# Statement of Account (SOA) — Design

**Status:** Approved (brainstorming) — ready for implementation plan
**Date:** 2026-07-10
**Track:** R-01 Sales (Order-to-Cash) — the last remaining slice (9/10 → 10/10)

## Context

R-01's document chain is complete: Quotation → SO → DR → SI, plus Credit Memo, Debit Note,
and CRV collection (including collecting a debit note, Phase 2b). What's missing is the
customer-facing **Statement of Account** — the periodic document you send a customer showing
what they owed at the start of a period, every charge and payment during it, and what they owe
now. Today CAS has an **AR Aging** report (`app/reports/views.py::_build_ar_aging_data`) that is
invoice-only and an as-of snapshot — it cannot show a customer their transaction activity or a
running balance, and it ignores debit-note balances.

The SOA is a **pure read/aggregation over existing posted data — no new model, no migration, no
new blueprint.** It reuses the report header/period/print/export machinery already in
`app/reports/`.

## Decisions (locked in brainstorming)

- **Form:** Balance-forward — opening balance, then every in-period charge and credit in date
  order with a running balance, a closing balance, and an aging summary. (Not open-item-snapshot.)
- **Run scope:** One customer per run (pick customer + period → View / Print / Excel). A
  "generate for all customers" batch is explicitly a **future** slice, not this build.
- **Branch scope:** **Current selected branch only** — consistent with the branch-scoped AR aging
  report and with how every AR document carries `branch_id`. (Not consolidated across branches.)
- **Opening balance presentation:** a single **"Balance forward"** line (a number as of the day
  before the period), not an itemized list of pre-period open documents.
- **Placement (Approach A):** read-only routes on the existing `reports_bp`, backed by a pure
  data-builder. Always-on report module (like `ar_aging`), per-user gatable via `book_permissions`
  — **not** an instance-level optional package.
- **Charge basis:** each charge = the document's `total_amount` (net of WHT — the actual
  receivable, and exactly what `balance = total_amount − amount_paid` is built from).
- **Aging:** full per-document reconstruction as of `period.date_to` (accurate for any historical
  period), buckets sum to the closing balance.

## Out of scope (record, do not silently drop)

- **Batch "all customers" run** — future slice; single-customer only here.
- **Consolidated (all-branch) statement** — current-branch only.
- **Itemized opening section** — single balance-forward line only.
- **Non-AR credit memos** (`destination` = `cash_refund` / `customer_credit`) — they never moved
  this customer's AR, so they never appear on the statement.
- **Emailing / PDF delivery** — the user prints or exports and sends manually.
- **e2e browser test** — read-only report with no document-submit JS; an optional light
  render-smoke may be added in the plan but is not required.

## Architecture (Approach A)

```
app/reports/
  statement_data.py                     NEW — pure builder (no Flask, no request)
  views.py                              +3 thin routes (screen / print / excel)
  templates/reports/
    statement_of_account.html           NEW — on-screen (filter bar + statement)
    statement_of_account_print.html     NEW — clone of general_ledger_print.html
app/users/module_access.py              +1 MODULE_REGISTRY entry (always-on report)
app/templates/base.html                 + _nav_ep + _nav_icon entries for the new key
app/customers/templates/customers/detail.html   + a "Statement" button (customer pre-filled)
```

No `models.py` change, no migration, no new blueprint.

### The data-builder

```python
def build_statement_of_account(customer_id, branch_id, period) -> dict
```

`period` is the dict returned by `resolve_period(request.args, today)` (from
`app/journals/ap_journal_data.py`) — `{mode, date_from, date_to, label, ...}`.

**Event collection** — all filtered by `customer_id` + `branch_id`, excluding voided/cancelled:

| Event | Source | Date | Amount | Sign |
|---|---|---|---|---|
| Invoice charge | `SalesInvoice`, status ∈ {posted, partially_paid, paid} | `invoice_date` | `total_amount` | + charge |
| Debit-note charge | `SalesMemo` memo_type='debit', status='posted' | `memo_date` | `total_amount` | + charge |
| Credit-memo credit | `SalesMemo` memo_type='credit', destination='ar', status='posted' | `memo_date` | `total_amount` | − credit |
| Payment | `CRVArLine` on a `CashReceiptVoucher` with status='posted' | `crv_date` | `amount_applied` | − credit |

A `CRVArLine` may reference an SI (`invoice_id`) or a debit note (`sales_memo_id`); both are AR
reductions — include both. The CRV's own `customer_id`/`branch_id` (header) scopes the query.

**Returned dict:**

```
{
  'customer':        {code, name, tin, address, payment_terms},
  'company':         get_company_identity(),          # name/tin/rdo/address for the header
  'period_label':    period['label'],
  'as_of_opening':   date_from - 1 day,               # label for the balance-forward line
  'opening_balance': Decimal,   # Σ charges(date < date_from) − Σ credits(date < date_from)
  'rows': [ {date, doc_type, doc_number, doc_id, particulars,
             charge: Decimal, credit: Decimal, running_balance: Decimal}, ... ],
             # events with date_from ≤ date ≤ date_to, sorted by (date, kind_rank, doc_number);
             # running_balance threads forward from opening_balance
  'total_charges':   Decimal,   # Σ period charges
  'total_credits':   Decimal,   # Σ period credits
  'closing_balance': Decimal,   # opening + total_charges − total_credits
  'aging':           {current, d1_30, d31_60, d61_90, d90_plus, total},   # of the closing balance
}
```

`kind_rank` gives a deterministic order for same-date events (e.g. charge before credit; SI
before DN before CM before CRV), so the running balance is reproducible.

On the screen version each row's `doc_number` links to that document's detail
(`sales_invoices.view` / `sales_memos.debit_view` / `sales_memos.credit_view` /
`cash_receipts.view`) via `doc_type` + `doc_id`.

### Aging summary (as-of `date_to` reconstruction)

The live `balance` field is as-of-*now*; the statement ages as-of `period.date_to`. For each
charge document (SI + posted debit note) dated `≤ date_to`, reconstruct:

```
balance_as_of(date_to) = total_amount
   − Σ CRV applications to that document with crv_date ≤ date_to
   − Σ credit-memo (destination='ar') against that SI with memo_date ≤ date_to   # SI only
```

Only positive remainders are aged. Bucketing date via `calculate_age_bucket(bucket_date, date_to)`:
- **Sales Invoice** → `due_date` (fall back to `invoice_date` if null).
- **Debit note** → `memo_date` (it has no `due_date`).

**Invariant:** the five bucket totals sum to `closing_balance` (tested). When `date_to = today`,
this reconstruction equals the live `balance` fields, so the SOA aging agrees with the existing AR
aging report for the current-date case.

## UI / outputs

**Screen** — `reports/statement_of_account.html`:
- Filter bar: customer picker (Choices.js, `code — name`), period control (`resolve_period`:
  month or custom range, mirroring the General Journal), **View / Print / Excel** buttons.
- Header block: company identity + customer (name, TIN, address, terms).
- Body: `Balance forward (as of <date_from − 1>)  <opening_balance>`, the running-balance table
  (Date · Doc # · Particulars · Charge · Credit · Balance), `Closing balance`, aging strip.
- Empty period: "No activity in this period." with opening = closing still shown.
- **No currency symbol on screen** (house rule) — bare numbers, "Amounts in PHP" stated once.

**Print** — `reports/statement_of_account_print.html`, cloned from `general_ledger_print.html`:
`bir_book_header(company, 'STATEMENT OF ACCOUNT', period_label)` + customer block,
`body onload="window.print()"`, the same table, closing + aging. The printout uses the `₱`
glyph like the other BIR books.

**Excel** — `export_to_excel`: title rows (customer, period), the same columns, opening/closing/
aging rows. **No CSV** (matches the financial-statements convention).

**Access:** `accountant_or_admin_required` (as GL/aging) + per-user `book_permissions` gating via
the registry key.

## Registration wiring (exploration-flagged)

1. **`MODULE_REGISTRY`** (`app/users/module_access.py`): add
   ```python
   {'key': 'statement_of_account', 'label': 'Statement of Account',
    'area': 'Sales', 'group': 'Reports', 'section': 'Ledger',
    'endpoints': ('reports.statement_of_account', 'reports.statement_of_account_print',
                  'reports.statement_of_account_export_excel')}
   ```
   — no `optional` flag (always-on, per-user gatable), like `ar_aging`.
2. **`base.html`**: add `statement_of_account` to **both** `_nav_ep`
   (→ `'reports.statement_of_account'`) and `_nav_icon` (an emoji). A registry key missing from
   `_nav_ep` raises `KeyError` on every page render.
3. **Customer detail** (`app/customers/templates/customers/detail.html`): a **"Statement"** button
   linking to `reports.statement_of_account` with `customer_id` pre-filled and the current month
   as the default period.
4. Routes live on the existing `reports_bp` — no blueprint registration needed in `create_app`.

## Edge cases

- Voided / cancelled SIs, voided memos, cancelled / voided CRVs — excluded.
- Credit memo with `destination ≠ 'ar'` — excluded (never touched AR).
- Debit note with no `due_date` — aged by `memo_date`.
- Customer with zero activity — opening = closing, empty table, aging all zero.
- Partially-paid SI straddling the period — charge falls in the opening balance, its later CRV
  payment appears as an in-period credit row.
- Same-date events — deterministic order via `kind_rank`.
- `date_to = today` — SOA aging must equal the live AR aging report for the same customer/branch.

## Testing (TDD)

`tests/unit/test_statement_data.py` (pure builder):
- opening-balance reconstruction from pre-period events (charges − credits dated < date_from);
- running balance threads correctly through mixed charges/credits in date order;
- **closing_balance == opening + Σcharges − Σcredits** (period tie-out);
- **aging buckets sum to closing_balance** (aging tie-out invariant);
- as-of-today aging equals the live AR-aging figures for the same customer;
- exclusions: voided SI, voided memo, cancelled CRV, non-AR (cash_refund/customer_credit) credit
  memo, other-branch and other-customer documents;
- debit-note charge + collecting-a-debit-note payment both appear;
- empty-activity customer → opening == closing, no rows.

`tests/integration/test_statement_of_account.py` (routes):
- screen route renders 200 with the customer header, balance-forward line, and rows;
- print route renders the `bir_book_header` title + table;
- Excel export returns the xlsx content-type with the expected header row;
- access gate: an accountant/admin is allowed; a staff/viewer user is blocked (the
  `accountant_or_admin_required` decorator, matching GL/aging), and the sidebar link is hidden
  when the `statement_of_account` book-permission is not granted;
- period filter honored (custom date range narrows the rows; a mismatched range shows opening=closing).

Optional (plan may include, not required): a light e2e render-smoke that the report page loads
with the customer picker under the `sales` seed profile.

## Verification

- **Unit/integration:** `venv/Scripts/python.exe -m pytest tests/unit/test_statement_data.py
  tests/integration/test_statement_of_account.py -q` — reconstruction math, both tie-out
  invariants, exclusions, route + gate + export.
- **Manual/MCP:** with a customer who has a posted SI, a debit note, a credit memo (ar-dest), and a
  CRV collection, open the SOA for the month → confirm the balance-forward number, the four row
  types with a correct running balance, the closing balance, and that the aging buckets sum to the
  closing balance and match the AR aging report when the period ends today.
- **Guard:** run `/guard cas` before any push (touches `module_access.py` + `base.html` — high
  blast radius). Push/deploy only on explicit user go.
