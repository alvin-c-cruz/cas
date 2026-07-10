# Debit Note Phase 2b — Collection Loop (CRV settles a debit note)

**Date:** 2026-07-10
**Track:** R-01 (Order-to-Cash) — completes the Debit Note (Phase 2a shipped the document).
**Status:** design approved (brainstorming); ready for writing-plans.

## Problem

Phase 2a ships the Debit Note document: it posts `Dr AR` (a supplementary charge that increases
the customer's receivable), but there is no way to **collect** it — the CRV collects only Sales
Invoices, and `SalesMemo` has no per-document balance. So a debit note's receivable sits in the AR
control account with no discrete open-item to settle. Phase 2b makes a posted debit note a
first-class open receivable that a Cash Receipt collects exactly like an invoice.

## Approach (chosen)

A debit note becomes a collectible AR document with its own `balance`; the CRV's AR line is made
**polymorphic** so a line references *either* a Sales Invoice *or* a debit note.

### Model changes (require sign-off before models.py / migration)

- **`SalesMemo`** (`app/sales_memos/models.py`): `+ amount_paid Numeric(15,2) NOT NULL default 0`,
  `+ balance Numeric(15,2) NOT NULL default 0`. Debit-note-only; credit memos leave both 0.
- **`CRVArLine`** (`app/cash_receipts/models.py`): `invoice_id` → **nullable**; `+ sales_memo_id
  Integer FK sales_memos.id nullable` (+ `sales_memo` relationship). Exactly one of
  `{invoice_id, sales_memo_id}` is set per line (enforced in the parser, not the DB — SQLite FK
  enforcement is off app-wide).
- **One hand-written batch migration:** add 2 columns to `sales_memos`; add `sales_memo_id` +
  relax `invoice_id` NOT NULL on the CRV AR-line table (`cash_receipt_ar_lines`). Relaxing NOT NULL
  is a batch table-rebuild → **verify on a copy of the real `cas.db`** (migration-verify rule);
  add `sales_memo_id` as a plain Integer if inline FK trips "Constraint must have a name".

### Behavior

- **Balance-only tracking** (no new status values). A debit note is "open" when
  `status=='posted' AND balance>0`. When `balance` reaches 0 it is fully collected; the UI shows
  "Collected" but the status stays `posted`. The shared `SalesMemo` status enum
  (`draft|posted|voided`) is unchanged.
- **Debit-note post** (extend `sales_memos.views._post_impl` — the generalized post shared by both
  memo types): on posting a debit note, set `balance = total_amount`, `amount_paid = 0`.
  Credit-memo post leaves balance 0.
- **CRV open-items** (`cash_receipts.views.open_invoices`): return posted SIs (balance>0) **and**
  posted debit notes (`memo_type='debit'`, balance>0) for the customer/branch, each tagged
  `{type: 'invoice'|'debit_note', id, number, balance, date}` → one **unified, tagged** list in
  the CRV picker.
- **CRV parse** (`_parse_line_items`): build a `CRVArLine` referencing the SI (`invoice_id`) or the
  debit note (`sales_memo_id`) per the picked item's type; snapshot the doc number into
  `invoice_number`; guard `amount_applied <= that doc's balance`.
- **CRV apply** (`_apply_ar_collections`): for each AR line, resolve the target (SI or debit note);
  `amount_paid += amount_applied`, recompute `balance`. SI keeps its existing status flip
  (`paid`/`partially_paid`); a debit note is balance-only (no status change).
- **CRV reverse** (`_reverse_ar_collections`, on CRV cancel): mirror — restore `amount_paid`/
  `balance` on either doc type.
- **CRV JE unchanged**: `Dr Cash · Cr AR (10201)` for the applied total, regardless of source — a
  collection credits the AR control account the same way for both document types.
- **Debit-note void guard** (extend `sales_memos.views` debit void): **block when
  `amount_paid > 0`** → "Cannot void a Debit Note with collections applied; reverse the Cash
  Receipt(s) first." Mirrors the SI cancel rule.

## Out of scope

- Credit memos are never collectible (excluded from the CRV picker; `balance` stays 0).
- No line-splitting beyond `amount_applied`; no cross-branch collection.
- No CRV form-JS overhaul — the existing open-items picker is extended to render the tagged list;
  the AR-line grid already keys on the returned `{id, number, balance}` shape.
- COGS / R-03 untouched.

## Components / files

- `app/sales_memos/models.py` — `amount_paid` + `balance`; set on debit-note post.
- `app/sales_memos/views.py` — post sets `balance=total_amount` (debit); void guard on collections.
- `app/cash_receipts/models.py` — `CRVArLine.sales_memo_id` + nullable `invoice_id`.
- `app/cash_receipts/views.py` — `open_invoices` union; `_parse_line_items` / `_apply_ar_collections`
  / `_reverse_ar_collections` resolve either doc type; JE-preview + print render debit-note lines.
- `app/cash_receipts/templates/.../form.html` — the picker renders the type tag (minimal).
- One migration under `migrations/versions/`.

## Error handling

- `amount_applied > balance` on a debit note → `ValueError` at parse/apply → CRV create rolls back.
- A debit-note AR line whose memo is not posted / not a debit note / wrong branch → raise (fail-closed).
- Void of a collected debit note → blocked with a clear flash (above).

## Testing (TDD)

- `open_invoices` includes a posted debit note with balance>0 (tagged), excludes collected ones and
  credit memos.
- CRV collects a debit note → its `balance` drops by `amount_applied`; full collection → balance 0,
  drops from a later picker.
- CRV cancel restores the debit note's balance.
- Void blocked when `amount_paid>0`; allowed (reverses JE) when uncollected.
- **Regression:** a plain SI collection still works (balance/status unchanged behavior).
- Migration verified on a copy of real `cas.db` (nullable-relax + new columns).
- e2e (optional): pick a customer with a posted debit note → it appears in the CRV open-items →
  collect → balance drops.
