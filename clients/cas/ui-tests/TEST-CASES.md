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
   Sales-VAT categories, Control Accounts, and the `uitest_ca` CA user that several specs assume.
   **Required run order** (the CA user must be registered LAST — see the script's own docstring for
   why: registering it earlier breaks admin's sole-full-access auto-approve for VAT/WHT/Sales-VAT):
   ```
   _shared_setup_cas_scope.py  →  vt_wt_crud_cycle.py  →  customers_vendors_crud_cycle.py  →  ca_registers_and_edits_perms.py
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

**T1.1 — Sales Invoice (SI) CRUD + posting.**
- *Intent:* SI create → post → JE; the actual heart of CAS. No spec exists yet.
- *Acceptance:* create/edit/cancel lifecycle; posting produces a balanced JE with each non-plug leg
  tying to the SI header (AR == total receivable, Output-VAT == doc VAT, Sales == subtotal — memory
  `posted-je-leg-vs-source-header-invariant`); all 3 print surfaces (rule #9); audit + Action-Items
  badge move on every write (rule #7).
- *Target:* new `sales_invoice_crud_post.py`.

**T1.2 — Cash Receipt (CR) CRUD + posting.**
- *Intent:* collection against an SI (or standalone), posts + settles balance.
- *Target:* new `cash_receipt_crud_post.py`.

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
- 🔵 **FEAT-SIDEBAR-ACCORDION** (LOW) — OPEN. Sidebar sections should collapse each other (owner
  request), currently independent toggle.
- 🔵 **Backlog #156** — Products/UOM/Customers/Vendors codes should be per-client configurable;
  WHT/VAT/COA codes always mandatory. Design decision recorded, not scoped/built.
- 🔵 Other UX/feature (non-blocking, prior session): `BUG-SETTINGS-NEEDS-TABS`,
  `BUG-CA-ACCESS-GRID-POINTLESS`, `BUG-DR-DETAIL-GRID-UNSTYLED`, `BUG-DASHBOARD-ASOF-DEFAULT-EOM`,
  `FEAT-IS-BY-PRODUCT-LINE`.
- 🟢 Fixed-in-tree: `BUG-SIDEBAR-QUOTATIONS-ORDER` (Quotations first).

## Out of scope beyond this run (parked — don't forget)

Multi-branch flows; Credit/Debit memo deep-dive; Year-End Close; Opening Balances; viewer role;
concurrency/lost-update stress; deploy/backup paths; the full ERP-scope suite (see above).
