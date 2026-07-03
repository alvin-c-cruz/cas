# Transaction-Form Line-Item Component Standard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Status:** Scoped — not started. Derived from the CTO consult (2026-07-03) after Opening Balances shipped a hand-rolled line item.

**Goal:** Make every transaction form's line-item row reuse the shared pickers (`initSearchSelect`) and money-field helpers (`transaction-utils.js`) *structurally*, so a form physically cannot render a row without the wiring — and enforce it with a cheap grep guard in the pre-push hook. Convert existing forms **lazily** (on next touch, forced by the guard), never big-bang.

**Architecture:** Two Jinja line-item macros as the single source of truth — a **journal-line** (account + debit/credit: Opening Balances, Journal Voucher) and a **document-line** (description/product/qty/uom/up/amount/VT/WT/account: SI, AP, CDV, CRV), parameterized by slots. A ~30-line `.claude/lint_forms.py` denylist run from the existing pre-push hook fails the push if a transaction template contains a literal `<select>` or a bare money `<input>` outside the macros. One enforceable CLAUDE.md sentence points at the macros.

**Tech Stack:** Flask/Jinja macros, vanilla JS (unchanged shared files), Python (lint script), the existing `.claude/guard.py` + `githooks/pre-push` harness.

**Source:** CTO consult — recorded in `~/.claude/vorg/knowledge/cto.md` (2026-07-03) and the Opening Balances parity work (`2026-07-03-opening-balances-si-parity.md`).

## Global Constraints

- **Lazy conversion, not big-bang.** Do NOT convert AP/CDV/CRV/JV speculatively — each converts the next time it is touched, forced by the lint. Only OB (done) + the SSOT extraction happen in this pass.
- **No behavior change** to any already-working form during extraction — the macro must emit byte-equivalent (or verified-equivalent) markup + wiring to what the form renders today; verify each converted form's e2e smoke still passes.
- **No hardcoded styling; design tokens only. Peso literal `₱`. Cache-buster `?v=N` bump on any `app/static/*` edit.** (CLAUDE.md.)
- **Reuse, don't reimplement:** the macros wire the EXISTING `initSearchSelect(selectEl)` and `transaction-utils.js` helpers (`amtFmt`/`amtFocus`/`amtBlur`/`qtyBlur`/`upBlur`) — no new formatting logic.
- **Single `initSearchSelect`** confirmed (only `search-select.js:38`); if a divergent copy reappears, collapse to `(selectEl, options)`.

## Pre-work decision (do first)

- [ ] **Diff the SI row vs the JV/OB row markup to confirm the two-macro split.** If SI's document-line and the journal-line diverge structurally (they do: VAT-inclusive single-amount + product/qty vs plain account+debit/credit), keep TWO macros. If a later reviewer finds them reconcilable via slots, one macro is acceptable — but do not force it.

## Tasks

### Task 1 — `macros/journal_line.html` (generalize OB's `ob_row`)
- **Files:** create `app/templates/macros/journal_line.html`; modify `app/opening_balances/templates/opening_balances/form.html` to `{% import %}` it (replacing the local `ob_row` macro).
- Extract OB's existing `ob_row(accounts, line, editable)` into the shared macro verbatim (account `<select class="ob-account">` + `.ob-debit`/`.ob-credit` + `.ob-remove`), so OB renders identically.
- **Verify:** `pytest -m opening_balances tests/e2e/test_opening_balances_smoke.py` still 5/5 green; bump OB template `?v` if any static changes.
- This makes the journal-line SSOT real and ready for JV (next time JV is touched).

### Task 2 — `macros/document_line.html` (extract from SI)
- **Files:** create `app/templates/macros/document_line.html`; modify `app/sales_invoices/templates/sales_invoices/form.html` to build its row from the macro. SI is the most mature document-line template (canonical per the SI-consistency memory).
- Parameterize slots: `show_product`, `show_qty`, `show_uom`, `show_up`, `show_vt`, `show_wt` — so AP/CDV/CRV can later opt into their subset.
- Account `<select>` pre-tagged with the `initSearchSelect` hook; money `<input>`s pre-tagged with the `transaction-utils` classes/`onfocus`/`onblur`.
- **Verify:** `pytest -m sales_invoices tests/e2e/test_si_smoke.py` still green; SI form byte-diff reviewed for equivalence; `?v` bumped if static touched.

### Task 3 — `.claude/lint_forms.py` denylist + pre-push wiring
- **Files:** create `.claude/lint_forms.py`; modify `.claude/githooks/pre-push` to call it next to `guard.py`.
- Hardcode `TRANSACTION_FORMS` = the 6 line-item templates (SI, AP, CDV, CRV, JV, Opening Balances) and a `CONVERTED` set (initially: `opening_balances`, `sales_invoices`). For each CONVERTED template, FAIL if it contains a literal `<select` or a money `<input>` (`type="number"`, or `name` in `{amount,debit,credit,qty,quantity,unit_price,price,rate}`) not emitted via a macro import. Templates not yet in `CONVERTED` are skipped (no nag on un-migrated forms). Expanding `CONVERTED` as each form migrates is the ratchet.
- **Verify:** run `python .claude/lint_forms.py` → passes on the current tree (OB + SI converted); temporarily re-add a literal `<select>` to confirm it FAILS; revert.

### Task 4 — CLAUDE.md rule + regression-map macro entries
- **Files:** modify `projects/cas/CLAUDE.md` (Project Conventions) — one line: *"Transaction line-item rows MUST be rendered via `macros/journal_line.html` or `macros/document_line.html`; no literal `<select>` or bare money `<input>` in a transaction-form template (enforced by `.claude/lint_forms.py`)."*
- Modify `.claude/regression-map.json`: add the two macro files as blast-radius keys → their consumer modules. (Note: the `search-select.js` dependents gap — missing `sales_invoices`/`cash_receipts` — was already fixed in the OB parity commit `3c5ec5f`.)
- **Verify:** JSON parses; CLAUDE.md rule is greppable.

## Deferred (lazy, not in this pass)
- Convert **AP, CDV, CRV** onto `document_line.html` and **JV** onto `journal_line.html` — each the next time it is touched for feature work, forced by the lint once added to `CONVERTED`. Riding existing edits (already smoke-tested) avoids regressing four working forms for no user-visible gain.

## Risks (from the CTO)
- **Macro rigidity** → use slots, not per-form copies, or it degrades to copy-paste.
- **Grep false-negatives** → a clever hand-roll dodges the regex; accepted (lint catches common drift; e2e smokes backstop behavior).
- **Converting working forms can regress money-format/picker-init with no JS unit net** → why conversion is deferred to when a form is already open and smoke-tested.
- **Guard fatigue** → the `CONVERTED` set scopes the lint so it never blocks work on a form not yet chosen for migration.
