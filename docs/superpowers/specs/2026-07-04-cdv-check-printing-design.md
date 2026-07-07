# CDV Check Printing + Per-Account Editable Layout — Design

- **Date:** 2026-07-04
- **Status:** SUPERSEDED (2026-07-07) by `plans/2026-07-07-cdv-check-writer.md`. This design's engine
  premise — an `app/preprinted_forms/` `PrintLayout`+FPDF stack — **does not exist in the codebase** (never
  built). The real engine is the 2026-07 HTML-canvas pre-printed system. Only the money-correctness, gating,
  audit, and test requirements below survive (carried into the new plan). Do NOT implement from this doc.
- **Module:** `app/preprinted_forms/` + `app/cash_disbursements/`
- **Origin:** User request — "CDV should be able to print over checks; user should be able to edit the print layout." Refined via boardroom (CEO/CTO/PM/Engineer/QA) + user decisions.

## Summary

Let a Cash Disbursement Voucher (CDV) print a data overlay onto a **physical pre-printed check**,
using an **editable layout that is per cash/bank account** (a Default layout plus per-account
overrides). This reuses the existing P-69 pre-printed-forms engine by adding a `CD_CHECK` layout
slot and an `account_id` dimension to `PrintLayout`. A "Print Check" action appears on a CDV only
when it is paid by check; the printed check ties out to the posted CDV amount.

## Background — what already exists (P-69 pre-printed forms)

`app/preprinted_forms/` is a complete feature:
- `PrintLayout` (models.py): one row per `voucher_type` (SI/CR/CD/AP/JV), `voucher_type` **UNIQUE**;
  `active` (admin toggle), `background_image` (uploaded form scan), `page_width_mm`/`page_height_mm`
  (default 215.90×279.40 = US Letter), `fields_json` (positioned header fields), `line_band_json`.
- `field_catalog.py`: `FIELD_CATALOG[vt]` header fields + line columns + resolvers, and a pure-python
  `amount_in_words`. `CD` already resolves `check_number`, `check_date`, `payee` (=`vendor_name`),
  `total` (=`total_amount`), `amount_in_words`.
- `pdf.py`: `render_preprinted(layout, record)` (FPDF data-only overlay; background only in `test=True`
  preview), `preprinted_response(vt, record)` (overlay PDF if module enabled + active layout + has
  background, else `None`), `can_print(vt, record)` (status/access gate; per-type `if/elif` + `else:
  return False`).
- `views.py`: designer (drag fields onto the background), admin toggle list, image upload,
  test-print, save — all keyed off the `voucher_type` string + `_TEST_PRINT_MODEL_NAMES`.
- CDV route `app/cash_disbursements/views.py::print_cdv` already calls `can_print('CD', cdv)` then
  `preprinted_response('CD', cdv)` before the HTML `print.html` fallback.

**The gap:** the engine allows exactly one layout per voucher type, and a check is a *separate
physical form from the CDV voucher* — and, per the user, its layout must vary **per bank/cash
account**.

## Requirements (locked with user 2026-07-04)

1. A **separate check layout**, distinct from the CDV voucher layout; a check-paid CDV can print
   **both** the voucher and the check (two outputs, different paper).
2. Trigger: a **"Print Check"** button on the CDV, shown **only when `payment_method == 'check'`**.
3. The check layout is **per cash/bank account**: a **Default** layout, plus per-account overrides
   the user can edit & save. Resolution is **tied to the cash/bank account chosen on the CDV**
   (`cash_account_id`).
4. The posted/draft gate is **configurable** (default posted-only; a setting allows printing on a
   **saved Draft** CDV). A check can **never** print on an *unsaved* voucher.
5. Every check print is **audited**.
6. Keying approach: **Option A** — reuse the `voucher_type` layout slot (`CD_CHECK`) + add
   `account_id`; do NOT introduce a `variant` column.

## Data model change (requires migration; approved by user)

Extend `PrintLayout` (`app/preprinted_forms/models.py`):

| Change | Detail |
|---|---|
| `account_id` | New nullable `db.Integer FK → accounts.id`, indexed. `NULL` = the **Default** layout for that slot; a value = that cash/bank account's override. |
| Unique key | Replace `UNIQUE(voucher_type)` with composite **`UNIQUE(voucher_type, account_id)`**. (SQLite treats multiple `NULL`s as distinct — enforce a single Default per slot in application logic, not by the DB unique.) |
| `voucher_type` width | Widen `String(8)` → **`String(16)`** (`'CD_CHECK'` fills 8 exactly; leaves headroom). |
| Page dims | `save()` must now **persist `page_width_mm`/`page_height_mm`** (today it writes only `fields_json`/`line_band_json`, so a check is stuck at Letter — the feature's premise is a different paper size). |

- One Alembic migration: add column + index, swap the unique constraint (batch_alter for SQLite),
  widen the column. No data backfill (existing 5 rows keep `account_id = NULL`).
- **Single-Default guard:** creating/saving a Default (`account_id IS NULL`) for a slot must not
  duplicate an existing Default — enforced in the view layer (`_get_or_create_layout` keyed by
  `(voucher_type, account_id)`).

### `CD_CHECK` field catalog

Add `FIELD_CATALOG['CD_CHECK']` (must include **both** `header` and `line_columns` keys; the
designer indexes `catalog['line_columns']`):

```python
'CD_CHECK': {
    'header': [
        _hf('check_date', 'Check Date', _attr_date('check_date')),
        _hf('payee', 'Payee (Vendor)', _attr_str('vendor_name')),
        _hf('total', 'Amount (Figures)', _attr_money('total_amount')),
        _hf('amount_in_words', 'Amount in Words', _amount_in_words_of('total_amount')),
        _hf('check_number', 'Check Number', _attr_str('check_number')),
        _hf('memo', 'Memo', _attr_str('notes')),
    ],
    'line_columns': [],   # a check has no line band
}
```

No `_LINE_ATTR['CD_CHECK']` entry → `iter_lines` returns `[]` → `render_preprinted`'s band loop is a
safe no-op. Add `_TEST_PRINT_MODEL_NAMES['CD_CHECK'] = ('app.cash_disbursements.models',
'CashDisbursementVoucher')`, `VOUCHER_TYPES += ('CD_CHECK',)`, and
`VOUCHER_LABELS['CD_CHECK'] = 'Cash Disbursement — Check'`.

## Access control

- New setting **`cd_check_print_access`** (values `posted_only` [default] / `draft_and_posted`),
  independent of the voucher's `cd_print_access`. Register in `SETTINGS_KEYS` and seed defaults.
- `can_print` gains a **`CD_CHECK` arm** reading `cd_check_print_access` (status rule identical to
  CD: `posted` for posted_only; not voided/cancelled for draft_and_posted). This resolves the
  panel's Engineer-vs-QA split in favor of an explicit arm (needed for the independent setting).
- Editing layouts stays under the existing `_edit_required` (full access / accountant / staff with
  `print_layouts` grant); enabling stays `_admin_required`.

## Print flow

New route `app/cash_disbursements/views.py::print_check(id)`:

1. `cdv = _get_cdv_or_404(id)` — enforces "no check on an unsaved voucher" (must be a saved id).
2. If `cdv.payment_method != 'check'` → flash + redirect.
3. If `not can_print('CD_CHECK', cdv)` → flash + redirect (draft/posted per `cd_check_print_access`).
4. Guard money-sanity: `cdv.check_number` present AND `cdv.total_amount > 0`, else flash + redirect
   (never print a serial-less or zero/negative check).
5. Resolve the layout by account, with Default fallback:
   `layout = active CD_CHECK for account_id == cdv.cash_account_id`, else `active CD_CHECK for
   account_id IS NULL`.
6. If no resolved layout / no background → flash "No check layout configured for this account."
   and redirect. **Never fall through to an HTML voucher** (there is no HTML check template).
7. Else return the overlay PDF (`render_preprinted(layout, cdv)`), and `log_audit(module='cash_
   disbursements', action='print_check', record_id=cdv.id, record_identifier=cdv.cdv_number,
   notes=f'account={cdv.cash_account_id}')`.

`preprinted_response` is extended (or a sibling helper added) to accept the resolved layout /
account so the account→Default resolution lives in one place.

### "Print Check" button visibility (CDV detail)

Compute `check_layout_ready` in the CDV `view()` and gate the button. Show **only when ALL** hold:

| Condition | |
|---|---|
| `cdv.payment_method == 'check'` | it's a check payment |
| `module_enabled('preprinted_forms')` | feature on |
| an **active** `CD_CHECK` layout resolves for `cdv.cash_account_id` **or** the Default | printable |
| that layout has a `background_image` | designed |
| `can_print('CD_CHECK', cdv)` | status/access allows (posted, or draft if configured) |
| `cdv.check_number` present AND `cdv.total_amount > 0` | valid instrument |

Absence-tested with Jinja `{# #}` comments (never `<!-- -->`, which leak into `resp.data`), paired
with positive-case assertions. Button is a plain link (`target="_blank"`), no JS popup.

## Designer (per-account editing)

The check designer gets an **account selector**: "Default" plus each cash/bank account. The user
picks the context, uploads that layout's background, positions fields, sets page dimensions, and
saves — persisting a `PrintLayout` row for `(CD_CHECK, account_id)`. Printing a CDV then uses that
CDV's cash-account layout (Default if none). Designer/save/upload/toggle routes gain an optional
`account_id` parameter; when absent they operate on the Default (`account_id IS NULL`), preserving
current behavior for the 5 existing voucher overlays.

## Money-correctness (release-blocking)

A check is a negotiable instrument, so `amount_in_words` must be bulletproof:

1. **Overflow bug (must fix):** `_SCALES` stops at `'Billion'`, so an amount ≥ 1 trillion raises
   `IndexError`, which `resolve_field`'s bare `except` swallows → a **blank legal-amount line**.
   Extend `_SCALES` (add `'Trillion'`, `'Quadrillion'`) and/or explicitly refuse to render above the
   supported range. **Never emit a blank words line for an in-range amount.**
2. **Rounding consistency:** `amount_in_words` quantizes with `ROUND_HALF_EVEN`; the rest of CDV math
   uses `ROUND_HALF_UP`. Harmless today (`total_amount` is already 2dp) but align to `HALF_UP` and
   pin with a test.
3. **Amount source:** the check face value is `total_amount` (= AP applied + expense − WHT = the net
   cash actually disbursed). WHT is withheld, not paid to the payee — do not use a pre-WHT figure.

## Testing strategy (TDD — write red first)

- **`amount_in_words` boundary table:** `1.00`→"One Peso and 00/100", `2.00`→"...Pesos...", `0.00`,
  `0.05` (leading-zero centavos), `0.99`, `1000/1e6/1e9` (no stray "and"/dangling scale), `1001.00`
  (zero-chunk skip), teens/tens/hyphen (11/15/19/20/21), `999_999_999_999.99` (top of range),
  `1_000_000_000_000.00` (the ex-blank overflow case — now correct).
- **Three-way tie-out (the key money test):** for a posted CDV, printed figure `_fmt_money(total_
  amount)` == `amount_in_words(total_amount)` figure == the cash credited in the posted journal
  entry. (`/audit` spirit.)
- **Gate truth table + absence tests** (see visibility table): cash CDV hides the button; check CDV
  with inactive/no-background/draft-under-posted_only hides; missing `check_number` or `total ≤ 0`
  hides/blocks; posted check with a ready layout shows and returns `application/pdf`.
- **Account resolution:** a CDV on account X with an X-specific layout uses it; a CDV on account Y
  with no Y layout uses Default; no Default + no account layout → flash, no fallthrough.
- **`can_print('CD_CHECK')`** honors `cd_check_print_access` (posted_only vs draft_and_posted).
- **Audit:** each `print_check` writes a `log_audit` entry; designer save/toggle/upload for
  `CD_CHECK` audit with the account in the identifier.
- **Regression / stale-fail:** update `tests/unit/test_preprinted_model.py:16` (exact `VOUCHER_TYPES`
  tuple) as a justified stale-fail; add `CD_CHECK` to the loops in `tests/unit/test_field_catalog.py`
  and `tests/integration/test_preprinted_forms.py` (else they pass green without testing it —
  coverage hole).
- **Regression map:** add `app/preprinted_forms/pdf.py` and `field_catalog.py` → all affected modules
  in `projects/cas/.claude/regression-map.json` (shared by all overlays; currently missing), same
  commit.

## Release gate

- Money boundary suite + three-way tie-out green; no in-range amount yields a blank/crashed words
  line; HALF_UP alignment tested.
- Gate truth-table + absence tests (with positive pairs) green; zero/negative/serial-less checks
  cannot print.
- Account→Default resolution correct; no silent fallthrough to the voucher.
- 5 existing overlays not newly broken (`/guard` from `projects/cas`, user-invoked); stale set-assert
  updates reviewed and justified.
- Audit entries verified for print + design mutations.
- **Manual sign-off:** one physical test print on real pre-printed check stock (alignment via
  `render_preprinted(..., test=True)` background), verified by the user against a live check.
  Software tests cannot certify physical registration.

## Out of scope (v1)

- MICR (E-13B) encoding / magnetic ink line.
- Positive-pay export files.
- Check register, automatic check-number sequencing, check-stock inventory.
- Void / stop-payment / spoiled-check workflow and reissue (beyond the audit trail + a reprint
  confirm).
- Multi-currency / foreign checks; multiple checks per CDV (v1 = 1 CDV → 1 check).
- Check printing for cash-method CDVs.

## Open items to confirm before/at implementation

- **Legal-amount format** the bank expects (e.g. `PESOS … ONLY`, ALL CAPS, protective asterisks /
  leader dashes) — may change `amount_in_words` output and its tests.
- **≤ 0 handling:** block-at-print (design choice here) vs silently absolutise — spec blocks.
- **Reprints:** rely on the audit trail; optionally a CSRF HTML confirm modal on a second print
  (no JS popup). Full spoiled/void handling stays out of scope.
- Actual check **paper size(s)** per bank (drives page-dimension defaults).
