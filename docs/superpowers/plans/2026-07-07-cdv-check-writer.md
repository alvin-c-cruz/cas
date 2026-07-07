# CDV Check Writer — Implementation Plan

- **Date:** 2026-07-07
- **Status:** Ready — Phase 0 gate open; Phase 1 not started
- **Supersedes:** `specs/2026-07-04-cdv-check-printing-design.md` + `plans/2026-07-04-cdv-check-printing.md`
  (their engine premise — an `app/preprinted_forms/` `PrintLayout`+FPDF stack — **does not exist in the
  codebase**; only their money-correctness + gating + test requirements survive, carried in below).
- **Origin:** `/boardroom plan for the CDV check writer` (CTO/Engineer/PM/QA/CFO + synthesizer, 2026-07-07),
  building on this session's real HTML-canvas pre-printed engine.

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development (mandatory — a printed
> check is a negotiable instrument; write the failing test first, watch it fail, minimal code). Checkbox
> (`- [ ]`) steps. Model changes need explicit user approval before the migration.

## Goal

Let a **check-payment CDV** print a data overlay onto physical **bank-issued pre-printed check stock**:
payee / check date / amount-in-figures / **amount-in-words** / memo, positioned with the existing
drag-drop designer, **rendered to PDF** for reliable registration. Overprint-only (never a whole check,
no MICR, **no facsimile signature** — the wet signature is the binding control). The printed face ties
out to the posted CDV's cash disbursed.

## Engine reality (verified 2026-07-07)

The check writer is a **new clone of the current HTML-canvas engine** (SI/CRV/APV/CDV):
`app/<doc>/preprinted_layout.py` (sanitized JSON in `app_settings`, sanitize-on-read/write, SAFE_MARGIN=48
clamp) + `print_preprinted.html` (absolute `.pp-el` fields) + `<doc>_preprinted_designer.js/.css` +
`<doc>_print_form` setting + print-route branch + save route; shared `clean_texts`. The CDV *voucher*
pre-printed form already ships. `amount_in_words` exists **nowhere** (build fresh). `CDV.check_number` is a
bare `String(50)` with **no uniqueness**. `CDV.cash_account_id` **is** a real non-null FK today.
`CDV.total_amount` = AP-applied + expense − WHT = net cash disbursed = the JE cash-credit leg = the check
face value. Layout **fields have no `width`** (only line columns / JE bands do) — a spelled words line can
**overflow**, so a width must be added to the words field.

## Resolved architecture decisions (the three forks)

1. **Print output = server-side PDF (fpdf2), not HTML `@page`.** A check must register inside pre-printed
   boxes on bank stock; browser print applies its own scaling and silently depends on the user setting
   margins-none/scale-100%. Render the **same sanitized JSON** to PDF with `pt = px * 0.75`
   (`mm = px * 25.4/96`). The HTML `.pp-el` canvas stays for **design/positioning only**, plus a screen-only
   **scanned-check background image** (never emitted to the PDF). Confirm **fpdf2** is installed on
   PythonAnywhere before committing.
2. **Layout keyed per `cash_account_id`** (`cd_check_layout:<cash_account_id>`), with a `cd_check_layout:default`
   fallback (resolve account-specific, else Default). Each bank's check geometry differs; `cash_account_id`
   is a real FK now — **no dependency on the un-built BankAccount module**. Re-key to `bank_account_id`
   later = a one-line `_layout_key` change.
3. **Serial integrity = DB partial-unique index in v1** (`UNIQUE(cash_account_id, check_number) WHERE
   check_number IS NOT NULL`), PLUS an app-layer pre-save guard for the friendly flash. Duplicate live check
   is the **P0** defect; the app-only guard loses the TOCTOU race, so the DB constraint is the real guard.
   **Verify the migration on a COPY of real `cas.db`** (batch migrations keep old indexes → false green on a
   conftest `create_all()`). SQLite treats multiple NULLs as distinct, so cash-method CDVs (null serial)
   don't collide.

## Research (de-risks the gate)

PCHC (new check design eff. 2024-05-01, non-compliant rejected from **2025-07-01**; Memo Circ. 3814/3821)
**explicitly accepts machine-printed amount-in-words**
with no format restriction → the RIC-bank confirmation is now a **formality**, not a blocker. But: the
check **date must render `MM-DD-YYYY`** (engine `DATE_FORMATS` lacks a dash variant — add a check-specific
one) and figures use standard comma/period. NIL (Act 2031) **Sec. 17(b): the WORDS legally control** over
the figures — the number-to-words engine is the legally operative amount.

## Global constraints

- **No model/DB change except the one approved serial index** (get explicit approval before the migration).
  Layouts stay `app_settings`-only. The `width`-on-words-field is a layout-JSON schema addition (sanitizer),
  **not** a DB column.
- **Overprint-only; NEVER a facsimile signature** (assert its absence in output). **Never** fall through to
  an HTML voucher on a missing/invalid layout — flash and refuse.
- Face value = `total_amount` (net cash, WHT withheld); pin the non-plug JE legs to the header
  ([[posted-je-leg-vs-source-header-invariant]]); keep `wt_override` + `vat_override` fixtures.
- **No currency symbol** anywhere ([[no-currency-symbol]]); the words line ends `… AND nn/100 ONLY` (the
  "PESOS" word is a layout element so it can be omitted when the stock pre-prints it). No JS popups (CSRF
  HTML modals). Bump `?v=N` on every touched static asset in the same commit. Commit per task (main, no push;
  user runs `/guard cas`). Restart the dev server before browser-testing `.py` changes.
- v1 non-goals: MICR/E-13B, positive-pay, auto check-number sequencing, multi-check-per-CDV, printed
  signature, cash-method-CDV checks.

## Phasing

### Phase 0 — GATE (no code; runs parallel to RIC migration/BIR work; does not block Task 1)
- [ ] Chief Accountant (Valencia) confirms **in writing**: bank accepts machine-printed amount-in-words;
  physical check **sample + exact geometry**; the bank(s) ↔ `cash_account_id` mapping; monthly check volume;
  draft-print policy; signature is wet-ink-only.
- [ ] Lock the policy calls: **1 CDV → exactly 1 check** (v1); a **voided serial is RETIRED, never reused**;
  same-actor approve==print is an **advisory flag**, not a hard block (small-team reality).
- [ ] **DoD:** signed bank confirmation + one physical blank check in hand. **No `print_check` route is
  exposed until this closes.**

### Phase 1 — MVP (release-gated; ~4.5–5.0 dev-days). Order matters — amount-to-words FIRST.

**Task 1 — `app/common/amount_to_words.py` (TDD-first, the load-bearing piece).**
- [ ] **RED:** `tests/unit/test_amount_to_words.py` — ~28-case matrix BEFORE any code:
  `Decimal('0.00')`→raise; negative→raise; non-Decimal→TypeError; `>2dp`→raise (or HALF_UP, lock it);
  `>= Decimal('1e12')`→overflow raise; `1.00`→`ONE PESO … 00/100 ONLY` (lock singular/plural); exact pesos
  `… AND 00/100 ONLY`; centavo zero-pad (`5.05`→`… AND 05/100 ONLY`); Decimal-not-float split
  (`Decimal('1.10')`→`10/100`, never `1.10*100=109.999`); `0.99`; hyphenation (`21`→`TWENTY-ONE`); teens;
  no interior "AND" except before centavos; `105.00` (no "and" after hundred); thousand/million/billion
  scale words; `9,999,999,999,999.99` (Numeric(15,2) max) renders fully; `10.10` vs `10.01` distinct;
  ALL-CAPS invariant; always ends `" ONLY"` and contains `"/100"`.
- [ ] **The oracle (non-tautological):** write an **INDEPENDENT** `parse_words(str)->Decimal` in the test
  module (different code path from the speller); property test (`hypothesis`, 2dp, `[0.01, 9_999_999_999_999.99]`,
  ≥1000 samples): `parse_words(amount_to_words(x)) == x`. Negative property: a corrupted string (missing
  "ONLY"/scale word) fails `parse` → feeds the Task-4 presence/terminator guard.
- [ ] **GREEN:** ~40-line hand-rolled integer→words core (ones/teens/tens + thousand/million/billion/trillion
  group recursion) + a Decimal peso/centavo wrapper. **Do NOT** vendor `num2words` (extra deploy dep + PH
  post-processing anyway). Signature `amount_to_words(value: Decimal) -> str`.

**Task 2 — clone-and-strip the check designer** (per `cash_account_id`).
- [ ] **RED:** `tests/unit/test_cd_check_layout.py` — FIELD_KEYS = `payee, check_date, amount_figures,
  amount_in_words, memo`; sanitize/get/save; per-`cash_account_id` `_layout_key` + `:default` fallback;
  SAFE_MARGIN clamp; **words field carries a `width`** and it clamps.
- [ ] **GREEN:** `app/cash_disbursements/check_layout.py` cloned from `preprinted_layout.py`, **stripped** of
  COLUMN_KEYS/`_clean_columns`/`journalEntry`/`_clean_je`/`lineItems` (FIELD + TEXT only, ~130 lines).
  `LAYOUT_SETTING_KEY='cd_check_layout'`; key on `cash_account_id`. Add a check-specific `MM-DD-YYYY` date
  format. `cd_check_print_form` setting (on/hidden) in `company_settings` + `save_cd_check_layout` route
  (full_access + CSRF). Designer `cd_check_designer.js/.css` (FIELD+TEXT drag only) + a screen-only
  scanned-check **background image** upload (never in the PDF).
- [ ] Grep sibling settings **set-asserts** in the same pass — a new setting key + new FIELD_KEYS break stale
  set-assertions ([[feedback-required-field-breaks-old-tests]], bitten 4×).

**Task 3 — serial-integrity (model change — get approval).**
- [ ] **RED:** two posted check CDVs, same `cash_account_id` + `check_number` → second **rejected**; same
  number, different account → allowed; voided CDV → number retired (not re-issued); whitespace/case
  normalized before compare; blank serial on a check CDV → rejected at save.
- [ ] **GREEN:** hand-written `batch_alter_table` migration adding the partial-unique index
  `(cash_account_id, check_number) WHERE check_number IS NOT NULL`; app-layer pre-save guard raising a domain
  `ValueError` (surfaces verbatim; order domain→ValueError→Exception). **Verify on a COPY of real `cas.db`**
  after `flask db upgrade` ([[migration-verify-on-real-db-copy]]); note the residual TOCTOU is covered by the
  DB constraint, not the app guard.

**Task 4 — PDF `print_check` route (fpdf2).**
- [ ] **RED:** integration — gate truth-table at the **route** level: cash CDV → no route/404; check CDV
  posted → prints `application/pdf`; draft per `cd_check_print_access`; voided/cancelled → blocked; blank
  serial or `total_amount ≤ 0` → blocked; unsaved id → no route; missing/`hidden`/overflowing amount or
  words field → refuse (never render the voucher). Three-way tie-out `figures == parse(words) == JE
  cash-credit leg` incl. `wt_override` + `vat_override`. Audit row per print. **No facsimile signature**
  (assert absent). Route-level **absence** tests (not just a hidden button); Jinja `{# #}` near gated markup.
- [ ] **GREEN:** `print_check(id)` — resolve the layout by `cdv.cash_account_id` (Default fallback); bind
  `payee=vendor.name`, `amount_figures=total_amount`, `amount_in_words=amount_to_words(total_amount)` **in the
  route** inside `try/except ValueError` → flash + refuse (Jinja must not call the raising helper); in-route
  guard `figures == value-passed-to-words`; render to PDF via fpdf2 (`px*0.75→pt`), overlay-only; date
  `MM-DD-YYYY`; `log_audit(action='print_check', …)`. Confirm fpdf2 is a dependency first.
- [ ] "Print Check" button on the CDV detail, shown only when: `payment_method=='check'` AND module on AND an
  active layout resolves AND `can_print` (posted / draft per setting) AND `check_number` present AND
  `total_amount>0`. Plain link, `target="_blank"`, no JS popup.

**Task 5 — regression + guard.**
- [ ] Add `regression-map.json` edges: `app/common/amount_to_words.py` + `check_layout.py` +
  `print_check` → CDV check-print smoke; the migration → CDV post/void tests. Single-threaded baseline
  ([[pytest-xdist-masks-ordering-bugs]]). User-invoked `/guard cas` + `/run-tests cas` before push.

### Phase 2 — controls hardening (fold the cheap parts into the Phase-1 window)
- [ ] Read-only **check-disbursement register** over existing CDV data (filter `payment_method=='check'`:
  date, check#, bank/cash account, payee, `total_amount`, status, printed-by/at) — cheap detective control +
  bank-rec surface.
- [ ] Audited `reprint_check` / `void_check` actions behind a **CSRF confirm modal** (no JS popup); void marks
  status + **retires** the serial.
- [ ] Record distinct **approver-vs-printer** actors; a configurable **dual-signature threshold** that stamps
  a "REQUIRES TWO SIGNATORIES" flag + audit (advisory; wet-ink stays binding).

### Phase 3 — per-account calibration & multi-bank
- [ ] Per-`cash_account_id` **calibration test-print** with an adjustable global X/Y offset stored with the
  layout (empirical registration on real stock/printer).

### Phase 4 — deferred (explicitly OUT)
MICR/E-13B line, serial auto-numbering register, multi-check-per-CDV, printed signature, positive-pay.
Do NOT jump RIC's migration-balance / BIR-filing work.

## Release gate (all GREEN before go-live)
1. DB partial-unique `(cash_account_id, check_number)` verified on a **copy of real `cas.db`**; void retires
   the serial.
2. Independent spell↔parse round-trip oracle, ≥1000-sample property test passing.
3. Print-route refuses a **hidden / overflowing / missing-"ONLY"** amount or words field.
4. Three-way tie-out `figures == parse(words) == JE cash-credit leg`, incl. `wt_override` + `vat_override`.
5. Gate truth-table covered by **route-level absence** tests; no fall-through to voucher print.
6. **No facsimile signature** (asserted absent). Date `MM-DD-YYYY`; figures standard comma/period.
7. Full suite single-threaded green; 0 SQLAlchemy deprecation warnings preserved; audit-entry asserts on
   post/void/print.
8. **Manual, software-uncertifiable:** one physical test print on real bank stock, aligned within tolerance,
   serial-on-paper == `check_number`, wet signature applies cleanly — signed off by the accountant.

## Top risks
1. **Physical registration on real stock/printer** — empirical, un-unit-testable; the true estimate-killer,
   NOT the words algorithm. Budget Phase 3 calibration + the manual sign-off.
2. **Migration false-green** — verify the partial-unique index on a real-DB copy; `create_all()` won't prove it.
3. **Words-field overflow** — no width clamp today; land the added `width` in Task 2, not later.
4. **Fall-through to voucher print** on a missing/invalid layout — must flash, never render the voucher.
5. **Bank confirmation slips** — Phase 0 runs in parallel, but no `print_check` route ships until it closes.

## Open items to confirm (Phase 0)
- Exact bank legal-line house style (CAPS, `PESOS … ONLY`, protective fill) → pins `amount_to_words` output +
  the oracle parser.
- Peso singular vs always-"PESOS"; centavo form (`nn/100` vs "CENTAVOS").
- One bank/stock or several (drives when Phase 3 per-account layouts are needed).
- `cdv.notes` as memo source vs a dedicated check-memo field (the latter = a model change needing approval).
