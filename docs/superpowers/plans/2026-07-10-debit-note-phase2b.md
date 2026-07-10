# Debit Note Phase 2b (CRV Collection Loop) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Let a Cash Receipt collect a posted debit note like an invoice.

**Architecture:** A debit note gains a per-document `balance`; the CRV AR line becomes polymorphic
(references a SalesInvoice OR a SalesMemo). The CRV open-items list, parser, apply, and reverse paths
resolve either document type; the CRV JE is unchanged (`Dr Cash · Cr AR`). Balance-only tracking.

**Tech Stack:** Flask + SQLAlchemy 2.0 + Jinja; pytest + Playwright.

## Global Constraints

- **Model change** (approved in design; get the exact-field sign-off before editing `models.py`):
  `SalesMemo` `+ amount_paid`/`+ balance` (Numeric(15,2), NOT NULL, default 0); `CRVArLine`
  `invoice_id` → nullable + `+ sales_memo_id` (Integer FK `sales_memos.id`, nullable).
- Exactly one of `{invoice_id, sales_memo_id}` per AR line — enforced in the parser (SQLite FK off).
- Balance-only: a debit note is open when `status=='posted' AND balance>0`; no new status values.
- **CRV JE unchanged.** Credit memos are never collectible (`balance` stays 0; excluded from picker).
- Migration is **hand-written batch**; the `invoice_id` NOT-NULL relax is a table rebuild → **verify
  on a copy of real `cas.db`** (`flask db upgrade` + probe). Bare-Integer FK if the inline FK trips
  "Constraint must have a name".
- TDD; branch `feat/debit-note-2b` (off `main`); commit each task. No currency symbol; no JS popups;
  SQLAlchemy 2.0 (`db.session.get`).

## File structure

- `app/sales_memos/models.py` — `amount_paid` + `balance`.
- `app/sales_memos/views.py` — post sets `balance=total_amount` (debit); void guard on collections.
- `app/cash_receipts/models.py` — `CRVArLine.sales_memo_id` + nullable `invoice_id`.
- `app/cash_receipts/views.py` — `open_invoices` union; `_parse_line_items`/`_apply_ar_collections`/
  `_reverse_ar_collections` resolve either doc; JE-preview + print render debit-note lines.
- `app/cash_receipts/templates/cash_receipts/form.html` — picker renders the type tag (minimal).
- `migrations/versions/<rev>_debit_note_collectible.py`.

---

### Task 1: Model change + migration (+ balance-on-post)

**Files:** `app/sales_memos/models.py`, `app/cash_receipts/models.py`, `app/sales_memos/views.py`,
new migration; tests `tests/unit/test_sales_memo_model.py` (extend),
`tests/integration/test_debit_note_flow.py` (extend).

- [ ] **Step 1 — sign-off:** present the exact field list (above) and get explicit approval.
- [ ] **Step 2 — failing test:** (a) unit: a `SalesMemo(memo_type='debit')` created + a debit-note
  create/post integration test asserts `memo.balance == memo.total_amount` after post and
  `amount_paid == 0`. (b) a `CRVArLine` can be built with `sales_memo_id` set and `invoice_id` None.
- [ ] **Step 3:** run → FAIL (attributes missing).
- [ ] **Step 4 — implement:** add the columns to both models; in `_post_impl` (sales_memos.views),
  when `memo_type=='debit'` set `memo.balance = memo.total_amount`, `memo.amount_paid = 0` at post.
  Hand-write the batch migration (2 cols on `sales_memos`; `sales_memo_id` + relax `invoice_id`
  NOT-NULL on `cash_receipt_ar_lines`). Register nothing new (models already imported).
- [ ] **Step 5:** run → PASS. **Step 6 — verify migration** on a copy of `cas.db`
  (`flask db upgrade`; probe: insert a CRV AR line with `invoice_id NULL, sales_memo_id=…`).
- [ ] **Step 7:** commit.

### Task 2: CRV open-items unions debit notes

**Files:** `app/cash_receipts/views.py` (`open_invoices`); test `tests/integration/test_crv_collect_debit_note.py`.

**Produces:** each open-item tagged `{type:'invoice'|'debit_note', id, number, balance, date}`.

- [ ] **Step 1 — failing test:** seed a posted SI (balance>0) + a posted debit note (balance>0) for
  customer C; `GET /cash-receipts/open-invoices?customer_id=C` returns both, tagged; a
  fully-collected debit note (balance 0) and a credit memo are excluded.
- [ ] **Step 2:** run → FAIL (only SIs returned).
- [ ] **Step 3 — implement:** extend the query/response — union posted SIs (`status in
  ('posted','partially_paid')`, balance>0) with posted debit notes (`memo_type=='debit'`,
  `status=='posted'`, balance>0), same branch+customer; tag each; keep the existing SI shape keys
  plus `type`.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 3: CRV parse / apply / reverse resolve either doc

**Files:** `app/cash_receipts/views.py`; test extends `test_crv_collect_debit_note.py`.

- [ ] **Step 1 — failing test:** POST a CRV collecting a debit note (AR line tagged debit_note) →
  after post the debit note's `balance` drops by `amount_applied`; full collection → balance 0.
  Then cancel the CRV → the debit note's balance is restored. A `amount_applied > balance` line is
  rejected. An SI collection still works (regression).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3 — implement:** `_parse_line_items` reads each line's `type`; builds `CRVArLine` with
  `invoice_id` OR `sales_memo_id` set, snapshots the doc number into `invoice_number`,
  `original_balance` from the target's balance; guard `amount_applied <= balance`.
  `_apply_ar_collections`: resolve `ar_line.sales_invoice or db.session.get(SalesMemo,
  ar_line.sales_memo_id)`; `amount_paid += applied`, recompute `balance`; SI keeps its status flip,
  debit note balance-only. `_reverse_ar_collections`: mirror. CRV JE builder + preview: a debit-note
  AR line credits AR (10201) by `amount_applied` — same as an SI line (use `invoice_number` for the
  description). Keep the SI path byte-identical where possible.
- [ ] **Step 4:** run → PASS (incl. the SI regression). **Step 5:** commit.

### Task 4: Debit-note void guard (collections)

**Files:** `app/sales_memos/views.py` (debit void path); test extends `test_debit_note_flow.py`.

- [ ] **Step 1 — failing test:** a debit note collected by a CRV (`amount_paid>0`) → `POST
  /debit-notes/<id>/void` is blocked (status stays `posted`, flash names the reason); an uncollected
  posted debit note still voids (reverses JE).
- [ ] **Step 2:** run → FAIL (void succeeds despite collections).
- [ ] **Step 3 — implement:** in the void impl, when `memo_type=='debit'` and `amount_paid>0`, flash
  "Cannot void a Debit Note with collections applied; reverse the Cash Receipt(s) first." and return
  without voiding.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 5: CRV picker UI tag (+ JE-preview/print render)

**Files:** `app/cash_receipts/templates/cash_receipts/form.html` (+ its JS if the picker is JS-built);
`.../print` + JE-preview templates; test `tests/integration/test_crv_form_debit_note.py`.

- [ ] **Step 1 — failing test:** the CRV open-items picker response/render distinguishes a debit note
  (the `type` tag reaches the template/JS); a posted CRV that collected a debit note renders its
  number on the detail/print.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3 — implement:** the picker labels each row with its type (Invoice / Debit Note); the
  AR-line grid already keys on `{id, number, balance}`; ensure the submitted line carries the `type`
  so the parser routes it. Detail/print/JE-preview show the AR line's `invoice_number` (doc number)
  unchanged. Bump any edited static asset's `?v=`.
- [ ] **Step 4:** run → PASS. **Step 5:** commit.

### Task 6 (optional): e2e + regression-map

- [ ] Extend the `sales` seed profile with a posted debit note that has a balance; e2e: customer with
  a posted debit note → it appears in the CRV open-items → collect → balance drops. Wire
  `app/sales_memos/models.py` + the CRV files into the `cash_receipts` blast radius in
  `.claude/regression-map.json`. Commit.

## Self-review notes

- **Spec coverage:** model+balance (T1), open-items union (T2), parse/apply/reverse (T3), void guard
  (T4), UI/print (T5), e2e (T6) — all covered.
- **Type consistency:** an AR line is polymorphic via `{invoice_id | sales_memo_id}`; `type` tag flows
  picker → submit → parser. `balance`/`amount_paid` are Numeric(15,2) on both models.
- **Risk:** the batch NOT-NULL relax on `cash_receipt_ar_lines` (T1) — verify on a real-DB copy;
  and the CRV apply/JE path must not regress SI collection (T3 keeps the SI branch identical).

## Verification

- `pytest tests/integration/test_crv_collect_debit_note.py test_crv_form_debit_note.py
  tests/integration/test_debit_note_flow.py -q`
- Migration: `flask db upgrade` on a copy of `cas.db`; probe a debit-note AR line insert.
- Manual/MCP: post a debit note → open a CRV for that customer → it appears in open-items → collect
  part → debit note balance drops → collect the rest → it drops from the picker; cancel the CRV →
  balance restored; try to void the collected debit note → blocked.
- `/guard cas` before push (touches `cash_receipts` + `sales_memos` — high blast radius).
