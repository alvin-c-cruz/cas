# CAS `/ui-test` — Test Plan & Case Log

**Forward test plan** for the next `/ui-test cas` run, plus a compact record of what's already
covered. Each `.py` file in this directory is a durable, versioned regression case driven through
the real UI (Playwright/CDP) against the empty-schema `/ui-test cas` env. Everything is built
**through the UI** (no seeding). Built 2026-07-11; corrected + re-scoped 2026-07-12 after
`BUG-UITEST-SPECS-ASSUME-UNCAPTURED-SETUP` was found and partially fixed.

## Scope split: CAS vs ERP

This suite covers two scopes that must NOT be conflated:
- **CAS scope** (this workspace's current focus) — the accounting/BIR-compliance core: Chart of
  Accounts, VAT/Sales-VAT/WHT, Control Accounts, Customers/Vendors, Staff Management, Users/Approved
  Emails, Company Settings, and the Core 5 documents (Sales Invoice, Cash Receipt, Accounts Payable,
  Cash Disbursement, Journal Voucher).
- **ERP scope** (separate, later effort) — Units of Measure, Products, Quotations, Sales Orders,
  Delivery Receipts, and everything downstream of them (the O2C sales-pipeline layer). A **separate**
  ERP-scope fixture/setup is planned later — do not extend the CAS-scope setup below to cover these.

## How to use this (next run)

1. Provision: `/ui-test cas` (empty schema → register `admin` → build/reach state via the UI).
2. **Run the CAS-scope shared setup FIRST:** `_shared_setup_cas_scope.py` builds the COA, VAT/
   Sales-VAT categories, Control Accounts, WHT `WC010`, and Customer/Vendor `CASCUST1`/`CASVEND1`
   that several specs assume — all auto-approved while admin is still sole full-access. CA
   registration is a SEPARATE script, `_register_ca.py`, that must run LATER (see the shared
   setup's own docstring for why: registering CA before `vt_wt_crud_cycle.py`/`customers_vendors_
   crud_cycle.py` run breaks admin's sole-full-access auto-approve for those specs' own creates —
   confirmed the hard way 2026-07-12, a genuine fresh-provision run hit 0/4 instead of 10/10).
   **Required run order:**
   ```
   _shared_setup_cas_scope.py  →  vt_wt_crud_cycle.py  →  customers_vendors_crud_cycle.py  →
   _register_ca.py  →  ca_registers_and_edits_perms.py  →  sales_invoice_crud_post.py
   ```
   `first_run_admin_bootstrap.py` and `coa_crud_cycle.py` are self-contained and can run anytime
   (bootstrap must run before anything else, obviously — it creates `admin`).
3. **Step-8 regression:** re-run the CAS-scope specs above (the "Already covered — CAS scope" table)
   before new work; re-open any regressed bug. Run a spec with the CAS venv:
   `projects/cas/venv/Scripts/python.exe clients/cas/ui-tests/<file>.py`
4. Work the **Next-Run Backlog** top-down (Tier 1 → 3) — CAS-scope items only for now.
5. Graduate each new passing case into a `*.py` spec here and add a row to "Already covered".

---

## Already covered — CAS scope (verified standalone-runnable, 2026-07-12, after the shared setup)

| Spec | Covers | Checks |
|---|---|---|
| `first_run_admin_bootstrap.py` | Empty DB → register `admin` → active admin + `MAIN` branch; bypass closes after first admin | 8/8 |
| `coa_crud_cycle.py` | COA CRUD + approval (create/approve, update/approve, update/**reject**, delete/approve) | 6/6 |
| `_shared_setup_cas_scope.py` | **Not a test — the shared setup** the 3 specs below need. Builds COA, VAT/Sales-VAT, Control Accounts, `uitest_ca`. Run once per fresh provision, in the documented order. | n/a |
| `vt_wt_crud_cycle.py` | Purchase VAT / Sales VAT / WHT full CRUD (needs the shared setup's COA) | 10/10 |
| `customers_vendors_crud_cycle.py` | Customers + Vendors CRUD (direct-save; needs the shared setup's VAT categories) | 8/8 |
| `ca_registers_and_edits_perms.py` | CA registers accountant+staff; edits staff perms, **not** accountant's (needs `uitest_ca` from the shared setup) | 10/10 |
| `jv_entry_crud_post.py` | Journal Voucher: create (balanced draft) → read → post → cancel; all 3 print surfaces (current/preprinted/hidden); audit trail (needs accounts 1610/4110 from the shared setup) | 12/12 |
| `sales_invoice_crud_post.py` | Sales Invoice: create (VAT-inclusive + WHT) → verify VAT/WHT math + JE-leg tie-out (AR/Output-VAT/Sales/Creditable-WHT) → read → audit → post → all 3 print surfaces → cancel. Needs Customer `CASCUST1`, WHT `WC010`, account 1710 from the shared setup (folded in 2026-07-12). | 21/21 — was 20/21 (tripwire for `BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS`), fixed 2026-07-12 |
| `concurrency_jv_concurrent_create.py` | 3 concurrent `uitest_ca` sessions creating a new JV at once (owner-requested concurrency probe) | 2/2 — found + FIXED `BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS` for JV (silent retry) |
| `concurrency_si_concurrent_create.py` | Same probe, extended to Sales Invoice | 3/3 — found + FIXED (surfaced: fresh number + flash, verified no raw exception) |
| `concurrency_ap_concurrent_create.py` | Same probe, extended to Accounts Payable | 3/3 — found + FIXED (surfaced) |
| `concurrency_cd_concurrent_create.py` | Same probe, extended to Cash Disbursement | 3/3 — found + FIXED (surfaced) |
| `concurrency_cr_concurrent_create.py` | Same probe, extended to Cash Receipt | 3/3 — found + FIXED (surfaced) |
| `cash_receipt_crud_post.py` | Cash Receipt: create (standalone direct-revenue) → JE-leg tie-out (cash/revenue) → read → audit → post → all 3 print surfaces → cancel | 18/18 — was 16/18 (2 tripwires for `BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS`, route + button axes), both fixed 2026-07-12 |
| `sidebar_accordion.py` | Sidebar accordion: only one `.nav-label-collapsible` section expanded at a time (admin: areas + admin + accounting-oversight); re-click collapses to zero-open; single `sidebar:expandedSection` localStorage key; stale saved name falls back to first area; active nav-item's section overrides a saved value. `staff` section type not separately covered (see spec docstring) — the JS is section-type-agnostic. | 13/13 |

**Setup gap CLOSED 2026-07-12:** `_shared_setup_cas_scope.py` now builds Customer `CASCUST1`, Vendor
`CASVEND1`, and WHT `WC010` itself (auto-approved, admin still sole full-access at that point — see
the script's own docstring). **Real ordering bug found + fixed in the process:** an earlier version
of the shared setup registered `uitest_ca` as its own last step, which broke `vt_wt_crud_cycle.py`
(needs admin to still be sole full-access) the moment it ran afterward — confirmed via a genuine
fresh-provision run (0/4, not the expected 10/10; `ZZV` went `pending` instead of auto-approving).
Fixed by moving CA registration out into its own script, `_register_ca.py`, positioned AFTER
`vt_wt_crud_cycle.py`/`customers_vendors_crud_cycle.py` and BEFORE `ca_registers_and_edits_perms.py`.
**Verified full chain end-to-end on a fresh provision:** bootstrap (8/8) → shared setup → `vt_wt_
crud_cycle.py` (10/10) → `customers_vendors_crud_cycle.py` (8/8) → `_register_ca.py` →
`ca_registers_and_edits_perms.py` (10/10) → `sales_invoice_crud_post.py` (20/21 at the time,
now 21/21 since `BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS` was fixed 2026-07-12). Current run
order for a fresh provision:
```
_shared_setup_cas_scope.py -> vt_wt_crud_cycle.py -> customers_vendors_crud_cycle.py ->
_register_ca.py -> ca_registers_and_edits_perms.py -> sales_invoice_crud_post.py
```

**Partially CAS-scope (some checks depend on ERP-scope modules — those checks fail, the rest pass):**

| Spec | CAS-scope checks | ERP-scope checks (expected to fail without Products/Quotations/etc.) |
|---|---|---|
| `action_items_and_audit_log.py` | 9/12 pass: badge +1/-1 on pending/approve/reject, audit log renders + records account/customer/vendor/VAT/WHT/control-accounts/approved-email/auth events with correct actor, reject logs `action='reject'` | 3 fail: "audit recorded master-data creates (customer+products)" (products=None), "Sales-Area docs" (quotations/SO/DR all None), "module filter narrows" (products=0 rows) — all need the ERP-scope modules enabled |

## Already covered — ERP scope (NOT run/fixed by CAS-scope setup; out of scope for now)

These 9 specs need Units of Measure / Products / Quotations / Sales Orders / Delivery Receipts
enabled (all optional, default-disabled) plus product/customer test data with specific codes
(`GEN01`, `CUST01`/"ABC Trading") that nothing in the CAS-scope setup creates. **Do not attempt to
fix these until the separate ERP-scope setup effort begins:**

- `uom_products_crud_cycle.py`
- `quotation_flow_inline_customer.py` (creates the shared `CUST01`/"ABC Trading" customer other ERP
  specs then expect to already exist — must run FIRST among the ERP-scope specs)
- `quotation_crud_lifecycle.py`
- `sales_order_crud_lifecycle.py`
- `delivery_receipt_crud_lifecycle.py`
- `full_sales_area_as_ca.py` — **also has a STALE assertion**, independent of the setup gap: it
  expects Sales Invoice creation to be BLOCKED by `BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS`, which is
  already fixed on `main` — the assertion needs updating to expect SUCCESS once control accounts are
  assigned (not yet done; see `project-bug-tracker`).
- `chief_accountant_role_crud.py` — needs Quotations (`#customer_id_display` picker)
- `staff_sales_area_sod.py`
- `accountant_sales_area_sod.py`

---

## Next-Run Backlog (CAS scope only)

Each item: **intent · acceptance · target spec · readiness**.

### Tier 1 — Ready now (do first; nothing blocks these — biggest gap: ZERO coverage of the Core 5 documents)

**T1.1 — Sales Invoice (SI) CRUD + posting. ✅ DONE 2026-07-12 — `sales_invoice_crud_post.py`, 21/21.**
- Covers create (VAT-inclusive, WHT-applied) → JE-leg tie-out to header (AR/Output-VAT/Sales/
  Creditable-WHT) → read → audit → all 3 print surfaces → post → cancel.
- Originally 20/21 with an intentional tripwire that caught a real, previously-unknown bug,
  `BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS` — the `/print` route only checked `sv_print_form`, not
  `sv_print_access`, so a direct GET on a draft's print URL rendered 200 anyway. **Fixed 2026-07-12**
  (route now enforces both, matching the button) — spec is 21/21 as of the fix.
- Setup gap: depends on Customer `CASCUST1`, WHT `WC010`, and account 1710 not yet in the shared
  setup — see the gap note above the "Already covered" table.

**T1.2 — Cash Receipt (CR) CRUD + posting. ✅ DONE 2026-07-12 (standalone-revenue only) —
`cash_receipt_crud_post.py`, 18/18.**
- Covers the standalone direct-revenue-line CR (create → JE-leg tie-out → read → audit → post →
  all 3 print surfaces → cancel). The AR-settlement-against-an-existing-SI flow is a distinct
  scenario, not yet covered — a separate future spec.
- Originally 16/18: found a NEW sibling bug while building this (CR's Print button ignored
  `cr_print_form` entirely, only checked `cr_print_access`) — the inverse of the route-side gap,
  extending `BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS` to a button-side blind spot in AP/CD/CR too
  (SI's button was already correct). **Both axes fixed 2026-07-12** — spec is 18/18 as of the fix.

**T1.3 — Accounts Payable (AP) CRUD + posting.**
- *Intent:* vendor bill create → post → JE (AP, Input-VAT, WHT-payable per bucket tie to header).
- *Target:* new `accounts_payable_crud_post.py`.

**T1.4 — Cash Disbursement (CD) CRUD + posting.**
- *Intent:* payment against an AP bill (or standalone expense), posts + settles balance.
- *Target:* new `cash_disbursement_crud_post.py`.

**T1.5 — Journal Voucher (JV) CRUD + posting. ✅ DONE 2026-07-12 — `jv_entry_crud_post.py`, 12/12.**
- Covers create (balanced draft) → read → post → cancel, all 3 print surfaces, audit trail.
- Gotcha found + documented in the spec: changing `jv_print_form` requires `company_name` (a
  DIFFERENT tab on the same Company Settings form) to be non-empty, or the WHOLE multi-tab submit
  silently fails validation, discarding the print-form change too.
- Gotcha found + memory'd: rapid-fire scripted logins across many driver scripts can trip
  Flask-Limiter's login rate limit (`10/min; 50/hour`) well before any account lockout would —
  see memory `feedback-unblock-test-login-db-vs-restart`.

**T1.6 — Print surfaces on the Core 5 (skill rule #9).**
- *Intent:* cover all 3 print surfaces (printable form, pre-printed overlay, hidden/disabled button
  gated by `*_print_access`/`*_print_form`) for SI/CR/AP/CD/JV as each CRUD spec above is built —
  don't defer to a separate pass, bake it into T1.1-T1.5.

**T1.7 — Company Settings full CRUD (all 6 tabs).**
- *Intent:* Company Profile, Accounting, Documents & Print (incl. the module-gating fix from today),
  Administration, Logo, Packages — tested manually this session (2026-07-12), no committed spec.
- *Target:* new `company_settings_crud.py`.

**T1.8 — Approved Emails full workflow.**
- *Intent:* add (immediate + pending), approve, reject, delete (blocked when used), self-approval
  toggle — tested manually this session (2026-07-12), no committed spec.
- *Target:* new `approved_emails_workflow.py`.

**T1.9 — Tax-master withdraw (graduate today's fix).**
- *Intent:* per discipline #6, `BUG-TAXMASTER-RATECHANGE-STUCK-SOLE-ADMIN`'s fix (the withdraw
  action, merged to `main` @ `140e45c`) needs a regression spec reproducing the original stuck
  scenario and asserting the fix, across all 3 tax-master modules.
- *Target:* new `taxmaster_withdraw_pending.py` (the app-side pytest already has
  `tests/integration/test_taxmaster_withdraw_pending.py` — this is the BROWSER-level sibling).

**T1.10 — Docprint module-gate (graduate today's fix).**
- *Intent:* per discipline #6, `BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS`'s fix (merged to
  `main` @ `140e45c`) needs a browser-level regression spec.
- *Target:* fold into T1.7's `company_settings_crud.py`, or its own small spec.

**T1.11 — Concurrency: N same-role users creating a new record in the same document at once.
✅ DONE 2026-07-12, extended to ALL 5 Core documents, ALL 5 FULLY FIXED AND VERIFIED.**
- *Intent (owner-requested, then explicitly "extend"ed to the rest of the Core 5):* 2-5 simulated
  concurrent users, same document type, all creating a NEW record at (near) the same instant —
  does the app hold up under a genuine race, or silently lose work?
- *Technique:* Playwright opens N independent browser contexts (separate logins/cookies) to
  legitimately capture each session's cookies + CSRF token + pre-generated document number, then
  fires the actual concurrent POSTs via `requests.Session` + `threading.Barrier(N)` (Playwright's
  sync API isn't safe to drive across threads, so the timed collision itself uses plain HTTP, not
  Playwright objects).
- *Result:* found `BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS` (MEDIUM) — confirmed in **all 5**
  Core documents (`concurrency_{jv,si,ap,cd,cr}_concurrent_create.py`): 3 concurrent creates on
  each document all got the SAME pre-generated number; only 1 of 3 committed every single time,
  the other 2 silently lost their work (generic error for JV/SI; a friendlier but equally-lossy
  "number already in use" pre-check for AP/CD/CR — the pre-check narrows the window but doesn't
  close it). DB integrity itself always held (no duplicate number ever committed) — this is
  data-loss-under-contention, not corruption, across the board. See
  `docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md` (renamed internally to
  BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS, filename kept for continuity).
- *JV instance ✅ FIXED 2026-07-12 (commit `d537d47`):* `commit_with_renumber_retry()`
  (`app/utils/concurrency.py`) retries the commit with a fresh number instead of failing, silently
  (JV's number is a pure system sequence, nobody cares about a specific value).
  TDD-backed (`tests/integration/test_jv_number_race.py`, RED→GREEN confirmed).
  `concurrency_jv_concurrent_create.py` now 2/2.
- *SI/AP/CD/CR instances ✅ FIXED 2026-07-12 (commits `f7900f4` merge chain + `7dc761c`):*
  `fresh_number_if_collision()` (surfaced pre-check: regenerate + re-render + explanatory flash,
  never silently swap — these 4 numbers are user-editable pre-printed-serial fields, per each
  document's own forms.py) plus `flush_or_suggest_fresh_number()` as a required backstop — the
  pre-check alone is check-then-act and a genuinely simultaneous race can still slip past it to
  the real `db.session.flush()`; confirmed live (raw `sqlite3.IntegrityError` leaking through)
  before the backstop was added, confirmed CLOSED after (every losing response now shows the
  friendly fresh-number re-render, verified by inspecting actual response bodies, not just status
  codes). The backstop specifically checks the IntegrityError names the right column before
  treating it as this bug — CD has an unrelated second unique constraint (check_number per cash
  account) that must never be misdiagnosed. All 4 built via parallel subagents in isolated
  worktrees, backstop applied centrally afterward. TDD-backed
  (`tests/unit/test_concurrency.py::TestFlushOrSuggestFreshNumber` + each document's own
  `test_{si,ap,cdv,cr}_number_race.py`). Full suite: 2662 passed, 1 pre-existing unrelated
  failure. All 4 browser probes now 3/3 (integrity + "at least 1 committed" + "every loser got
  the friendly re-render, not a raw exception").

### Tier 2 — Ledger & Reports (needs posted data from Tier 1)

**T2.1 — Ledger.** General Ledger, Trial Balance balances, Books of Accounts render on the posted
JEs from T1.1-T1.5. *Target:* `ledger_reports_render.py`.

**T2.2 — Financial statements + BIR.** Income Statement / Balance Sheet / Cash Flow / AR-AP aging
tie out; BIR 2550Q / SAWT / 2307 render. *Target:* `financial_statements_render.py`.

### Tier 3 — Parked (own effort, not this pass)

Fiscal Year Close; Opening Balances; multi-branch flows; viewer role; concurrency/lost-update
stress; deploy/backup paths; ERP scope (see the "Already covered — ERP scope" section above).

---

## Open findings feeding the plan (see memory `project-bug-tracker` + `docs/bug-reports/`)

- 🟢 **BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS** (HIGH) — FIXED (merged before this session). SI/CR/
  AP/CDV posting now resolves control accounts from Settings, not hardcoded codes. `full_sales_area_
  as_ca.py`'s stale "expected blocked" assertion (ERP-scope, not fixed) is the residue of this.
- 🟢 **BUG-DR-EDIT-FALSE-CONFLICT** (HIGH) — status per prior session's notes; ERP-scope, not
  re-verified this session.
- 🟢 **BUG-TAXMASTER-RATECHANGE-STUCK-SOLE-ADMIN** (HIGH) — FIXED 2026-07-12, merged `main`@`140e45c`.
  Needs a browser spec (T1.9).
- 🟢 **BUG-SETTINGS-DOCPRINT-UNGATED-OPTIONAL-CONTROLS** (MED) — FIXED 2026-07-12, merged
  `main`@`140e45c`. Needs a browser spec (T1.10).
- 🔵 **BUG-TAXMASTER-STALE-PENDING-BLOCKS-RETRY** (LOW-MED) — OPEN. A tax-master spec re-run after an
  environment change (e.g. CA registered) can leave a stale pending request blocking retries;
  workaround (withdraw) exists, no automated guard yet.
- 🟢 **BUG-DOCPRINT-ACCESS-GATE-ROUTE-BYPASS** (MED) — FULLY FIXED 2026-07-12 (commit `6ac0a23`).
  Found via `sales_invoice_crud_post.py`'s tripwire, extended via `cash_receipt_crud_post.py` with
  a second addendum. Two complementary blind spots across SI/APV/CDV/CRV, both now closed:
  (a) *route side* — `/print` routes now enforce `*_print_access` (posted_only/draft_and_posted)
  in addition to `*_print_form`, mirroring the button's own logic (and `print_check`'s already-
  correct reference pattern).
  (b) *button side* — AP/CD/CR's Print buttons now also check `*_print_form != 'hidden'` alongside
  their existing `*_print_access` check, matching SI's button exactly.
  Verified live: both graduated specs are now full green (`sales_invoice_crud_post.py` 21/21,
  `cash_receipt_crud_post.py` 18/18). Full suite: 2681 passed, 1 pre-existing unrelated failure.
- 🟢 **BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS** (MED) — FULLY FIXED 2026-07-12, all 5 documents.
  Found via the concurrency probe (owner-requested, then "extend"ed to the full Core 5, then
  further hardened after empirically re-testing against a genuine tight race). JV fixed via
  silent `commit_with_renumber_retry()` (commit `d537d47`); SI/AP/CD/CR fixed via the surfaced
  `fresh_number_if_collision()` pre-check PLUS the required `flush_or_suggest_fresh_number()`
  backstop (commits in the `fix/{si,ap,cd,cr}-number-race` merge chain + `7dc761c` for the
  backstop) — the pre-check alone left a real gap under genuine simultaneous requests (confirmed
  live: the raw `sqlite3.IntegrityError` was leaking through before the backstop). All 5 browser
  probes verified: JV 2/2 (silent, all succeed); SI/AP/CD/CR 3/3 each (integrity + at-least-1-
  committed + every loser gets the friendly re-render, not a raw exception — verified by
  inspecting actual response bodies, not just status codes). See
  `docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md`.
- 🟢 **FEAT-SIDEBAR-ACCORDION** (LOW) — FIXED 2026-07-12. Replaced the N independent
  `sidebar:<name>` localStorage keys with a single `sidebar:expandedSection` key; clicking a
  section now force-collapses every other section (global, across area sections + Admin + Tax &
  Oversight + Staff Management), and re-clicking the open section collapses it too (zero-open is
  valid). Old per-section keys are left orphaned/unmigrated (accepted tradeoff). See
  `sidebar_accordion.py` (13/13).
- 🔵 **Backlog #156** — Products/UOM/Customers/Vendors codes should be per-client configurable;
  WHT/VAT/COA codes always mandatory. Design decision recorded, not scoped/built.
- 🔵 Other UX/feature (non-blocking, prior session): `BUG-SETTINGS-NEEDS-TABS`,
  `BUG-CA-ACCESS-GRID-POINTLESS`, `BUG-DR-DETAIL-GRID-UNSTYLED`, `BUG-DASHBOARD-ASOF-DEFAULT-EOM`,
  `FEAT-IS-BY-PRODUCT-LINE`.
- 🟢 Fixed-in-tree: `BUG-SIDEBAR-QUOTATIONS-ORDER` (Quotations first).

## Out of scope beyond this run (parked — don't forget)

Multi-branch flows; Credit/Debit memo deep-dive; Year-End Close; Opening Balances; viewer role;
concurrency/lost-update stress; deploy/backup paths; the full ERP-scope suite (see above).
