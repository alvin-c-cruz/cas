# Opening Balances — Sales-Invoice line-item parity

**Date:** 2026-07-03
**Status:** Design — approved, pending implementation plan
**Scope:** Front-end only (`/opening-balances`). No server/model/migration changes.
**Page:** `http://127.0.0.1:5050/opening-balances`

## Problem

The Opening Balances line-item grid does not behave like the transaction forms
(Sales Invoice / Accounts Payable). Two concrete gaps:

1. **Account field is a bare native `<select>`**, not the Choices.js search-select
   used everywhere else. No typeahead; the earlier CSS-only fix (`4306333`) merely
   widened the column so the title stops truncating.
2. **Debit/Credit inputs have no focus/blur formatting.** They accept raw text with
   no thousands separators and no on-blur normalization, unlike SI's amount fields.

## Goal

Bring the Opening Balances line item to parity with SI:

- The **Account** field is a Choices.js **search-select** (typeahead), initialised
  through the shared `initSearchSelect()`.
- The **Debit** and **Credit** fields get **onfocus / onblur** handlers and the
  standard **`1,234.56`** content format, reusing the shared `amtFmt` helper.

## Non-goals (YAGNI)

- No JE-preview / VAT / WHT panel — Opening Balances is a balance-entry grid, not a
  posting document. The existing Total Debit / Total Credit / Difference row is the
  balance check.
- No Journal Voucher changes. The same pattern could port to JV later; out of scope here.
- No server, model, or migration changes (see "Server: no changes" below).

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Which accounts appear in the picker? | **Keep today's list**: all accounts, group/parent headers `disabled` with indent dashes, `code : name` format. Choices renders disabled options fine. |
| Debit vs Credit both filled? | **Auto-clear the sibling**: entering an amount in Debit clears Credit on that row, and vice-versa, so a row can never hold both. |
| Blur display of a zero/blank amount? | **Stays blank** (not `0.00`), so it's visible at a glance which side a row uses. A value `> 0` formats as `1,234.56`. |

## Why front-end only (server already supports this)

`app/opening_balances/views.py`:

- `_to_decimal` (line ~53) does `Decimal(str(raw or '0').replace(',', '').strip() or '0')`
  — **already strips thousands separators**, so a submitted `1,234.56` parses correctly.
- `_parse_lines` already **rejects non-leaf accounts** (`account_id not in leaf_ids`) and
  **rejects a line with both debit and credit** (`raise OpeningLineError('… debit OR a credit, not both.')`).

So the formatting and auto-clear behaviours need no server support; they only make the
existing rules easier to satisfy in the UI.

## Architecture

**Approach: mirror SI's shared front-end stack; hybrid rendering.**
Server keeps rendering existing rows (edit mode); JavaScript upgrades each editable
account `<select>` to a search-select on load and builds *new* rows programmatically.
This is required because Choices.js wraps the `<select>` in extra DOM, so the current
`cloneNode`-based "+ Add line" cannot survive — new rows must be built from scratch
(the SI `addLineItem()` pattern).

### Components

1. **Template** — `app/opening_balances/templates/opening_balances/form.html`
   - Link shared assets in the content block: `choices.min.css`, `transactions.css`
     (CSS), and before the page script: `choices.min.js`, `search-select.js`,
     `transaction-utils.js`, then the rewritten `opening_balances.js?v=3`.
   - Emit the account list once as a JSON blob:
     `<script type="application/json" id="ob-accounts">[…]</script>` with
     `{id, code, name, depth, is_group}` per account — the data `obAddRow()` builds
     new rows from. Server continues to render existing entry rows as today.
   - Keep the `opening_balances.css` per-form stylesheet (already added in `4306333`);
     drop the now-unused native-`<select>` width rule, keep column widths + number-input styling.

2. **Account picker** — each row keeps `<select name="account_id" class="ob-account">`
   with the same options (all accounts; group headers `disabled` + indent dashes;
   `code : name`). On load, JS calls `initSearchSelect(selectEl)` on every **editable**
   row's select. Non-editable rows (posted / locked / read-only) stay plain disabled
   `<select>` — a read-only view needs no typeahead. Choices keeps the underlying native
   `<select>` synced, so the POST payload (`account_id[]`) is unchanged.

3. **Number fields** — Opening-Balances-specific helpers in `opening_balances.js`
   (reusing `amtFmt` from `transaction-utils.js`):
   - `obAmtFocus(el)` — strip commas to a plain editable number and `select()`; an
     empty/zero field stays empty.
   - `obDebitBlur(el)` / `obCreditBlur(el)` — parse (`parseFloat(value.replace(/,/g,''))`);
     `> 0` → `el.value = amtFmt(n)`, else `el.value = ''`; if `n > 0`, clear the sibling
     field on the same `.ob-line`; then `recalc()`.

4. **Row lifecycle** — `opening_balances.js`:
   - The initial empty row (when there is no saved entry yet) stays **server-rendered**,
     so the grid always opens with one row; JS upgrades it on load like any other editable row.
   - On load: for each editable `.ob-line`, `initSearchSelect` its `.ob-account`, and wire
     the debit/credit focus+blur handlers; then `recalc()`.
   - `obAddRow()` replaces the `cloneNode` handler: builds a fresh row (account `<select>`
     from the JSON blob + Debit/Credit text inputs wired to the handlers), appends it,
     `initSearchSelect`es it, and `recalc()`s.
   - Remove-row (`×`) and the balanced / Post-disabled logic are unchanged (they read
     `.ob-debit` / `.ob-credit` values).

5. **Server** — **no changes.** Comma-tolerant parse, leaf-only accounts, and the
   both-filled guard already exist.

### Data flow

```
page load
  ├─ existing rows (server-rendered) ──▶ initSearchSelect + wire focus/blur ──▶ recalc
  └─ "+ Add line" ──▶ obAddRow() builds row from #ob-accounts JSON ──▶ initSearchSelect + wire

user edits a Debit
  onfocus  ▶ obAmtFocus: strip commas → plain, select-all
  onblur   ▶ obDebitBlur: >0 → "1,234.56" (else blank) → clear Credit on row → recalc

submit (native form POST, unchanged)
  account_id[] / debit[] / credit[] ──▶ _parse_lines (strips commas, leaf-only, not-both)
```

## Error handling / edge cases

- **Read-only states** (posted, locked, not `editable`): render plain disabled selects,
  no Choices init; focus/blur handlers not wired.
- **Empty row on submit**: server already skips all-zero rows — unchanged.
- **Sibling auto-clear** fires only when the just-blurred field is `> 0`, so tabbing
  through an empty field never wipes a value the user already typed on the other side.
- **Choices ↔ native sync**: rely on Choices keeping `<select name="account_id">` in sync
  so the POST is unaffected; do not read Choices' internal state on submit.

## Testing

- **Playwright e2e smoke** — `tests/e2e/test_opening_balances_smoke.py`, marker
  `opening_balances` (register in `pytest.ini`):
  1. account picker is a Choices widget; pick an account via the dropdown.
  2. type a Debit, blur → asserts `1,234.56` formatting.
  3. entering a Debit `> 0` clears the Credit on that row (and vice-versa).
  4. "+ Add line" adds a working row with its own search-select.
  5. remove-row works; Total Debit / Total Credit / Difference update.
  6. submit a balanced draft → the draft persists with the correct amounts.
- **Unit test** — assert `_parse_lines` accepts comma-formatted `debit`/`credit`
  (e.g. `'1,234.56'`), pinning the "no server change needed" assumption.
- **Regression map** — add `opening_balances` to `.claude/regression-map.json`
  (module + `e2e` path) so the new JS surface is guarded.

## Files touched

- `app/opening_balances/templates/opening_balances/form.html` — asset links, `#ob-accounts` JSON blob.
- `app/static/opening_balances.js` — rewrite (search-select init, programmatic rows, focus/blur, auto-clear, recalc).
- `app/static/opening_balances.css` — drop the native-select width rule; keep the rest.
- `tests/e2e/test_opening_balances_smoke.py` — new e2e smoke.
- `tests/unit/…` — one comma-parse unit test for `_parse_lines`.
- `pytest.ini`, `.claude/regression-map.json` — register marker + guard the module.
- **No** changes to `app/opening_balances/views.py`, models, or migrations.
