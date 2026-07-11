# CAS `/ui-test` — Test Plan & Case Log

**Forward test plan** for the next `/ui-test cas` run, plus a compact record of what's already
covered. Each `.py` file in this directory is a durable, versioned regression case driven through
the real UI (Playwright/CDP) against the empty-schema `/ui-test cas` env. Everything is built
**through the UI** (no seeding). Built 2026-07-11.

## How to use this (next run)

1. Provision: `/ui-test cas` (empty schema → register `admin` → build/reach state via the UI).
2. **Step-8 regression first:** re-run all existing specs (the "Already covered" table) before new
   work; re-open any regressed bug. Run a spec with the CAS venv:
   `projects/cas/venv/Scripts/python.exe clients/cas/ui-tests/<file>.py`
3. Work the **Next-Run Backlog** top-down (Tier 1 → 3). Honor discipline: **log every bug first**
   (rule #3), cover **print surfaces** on document CRUD (rule #9), assert **Action Items + Audit
   Log** move on every write (rule #7), and **page-pause** for interactive flows (rule #8).
4. Graduate each new passing case into a `*.py` spec here and add a row to "Already covered".

---

## Next-Run Backlog

Each item: **intent · acceptance · target spec · readiness**.

### Tier 1 — Ready now (do first; nothing blocks these)

**T1.1 — Print surfaces on the Sales docs (skill rule #9).**
- *Intent:* backfill the three print surfaces onto the existing quotation/SO/DR CRUD specs, and
  cover SI/CDV/CRV/APV/JV print where reachable.
- *Acceptance:* (a) **printable form** `/<doc>/<id>/print` renders (right number, party, lines,
  totals) with no 500; (b) **pre-printed overlay** (`print_preprinted.html`) renders and honors the
  doc's `*_print_form` setting (current vs preprinted); (c) **hidden/disabled button** matches the
  `*_print_access` / `so_print_form=hidden` setting — assert the button is shown when allowed and
  **absent when not**, and that a direct GET of the print URL respects the same gate.
- *First confirm (candidate bug):* SO detail Print button renders **unconditionally**
  (`sales_orders/templates/sales_orders/detail.html:77`) while the view redirects when
  `so_print_form == 'hidden'` (`sales_orders/views.py:451`) — verify and log if the button shows
  under the hidden setting.
- *Target:* extend `quotation_*`, `sales_order_crud_lifecycle`, `delivery_receipt_crud_lifecycle`;
  new `print_surfaces_sales.py`.

**T1.2 — Journal Voucher (JV) CRUD + POST.**
- *Intent:* JV Entry create → post to the books. **Posts now** — JV uses user-picked accounts, so
  it is NOT gated by BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS (unlike SI/CR/AP/CDV).
- *Acceptance:* balanced JE created; number `JV-YYYY-MM-####`; create→post→**posted**; Dr==Cr and
  each leg ties to what was entered; cancel path + closed-period guard behave; audit entry +
  Action-Items badge move (rule #7). (JV segregation-of-duties already proven on RIC; here prove the
  full CRUD+post on the CAS env.)
- *Target:* new `jv_entry_crud_post.py`.

**T1.3 — Purchases Area (AP / CDV) write + lifecycle.**
- *Intent:* mirror the Sales-Area work on the buy side. Vendor already exists (build one via UI if
  not). AP voucher + Cash Disbursement create/edit/approve/lifecycle.
- *Acceptance:* AP + CDV create/edit/lifecycle work as the right role; **posting attempt is
  expected BLOCKED** by the same hardcoded-control-account bug — assert the block (documents the HIGH
  bug affects the buy side too, role-independent).
- *Target:* new `accounts_payable_crud_lifecycle.py`, `cash_disbursement_crud_lifecycle.py`.

### Tier 2 — Blocked until fix (gated on BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS)

Do NOT attempt posting-dependent assertions until the fix lands (settings-assigned control
accounts). Interim: adding magic-code accounts to the COA is a **workaround, not a fix** — flag it
if used only to smoke the chain.

**T2.1 — SI / Cash Receipt posting end-to-end.** bill a delivered DR → Sales Invoice → post → JE;
assert **each non-plug leg ties to the SI header** (AR == total receivable, Output-VAT == doc VAT,
Sales == subtotal — memory `posted-je-leg-vs-source-header-invariant`); Cash Receipt collection
posts + settles balance. *Target:* `si_posting_end_to_end.py`, `cash_receipt_posting.py`.

**T2.2 — AP / CDV posting end-to-end.** post → JE ties to header (AP, Input-VAT, WHT-payable per
bucket). *Target:* extend the Tier-1 AP/CDV specs with the posting assertions once unblocked.

### Tier 3 — After posted data exists (Ledger & Reports)

Read-mostly; needs posted transactions. **Partially reachable now** using T1.2's posted JVs, even
before the SI fix.

**T3.1 — Ledger.** General Ledger, **Trial Balance balances**, Books of Accounts render on the
posted JEs. *Target:* `ledger_reports_render.py`.

**T3.2 — Financial statements + BIR.** Income Statement / Balance Sheet / Cash Flow / AR-AP aging
tie out; BIR 2550Q / SAWT / 2307 render. *Target:* `financial_statements_render.py`.

---

## Already covered (regression baseline — run these first, Step-8)

| Spec | Covers | Checks |
|---|---|---|
| `first_run_admin_bootstrap.py` | Empty DB → register `admin` → active admin + `MAIN` branch; bypass closes after first admin | 8/8 |
| `coa_crud_cycle.py` | COA CRUD + approval (create/approve, update/approve, update/**reject**, delete/approve) | 6/6 |
| `vt_wt_crud_cycle.py` | Purchase VAT / Sales VAT / WHT full CRUD | 10/10 |
| `customers_vendors_crud_cycle.py` | Customers + Vendors CRUD (direct-save) | 8/8 |
| `uom_products_crud_cycle.py` | UOM + Products CRUD (deactivate, no hard delete); encodes `Pieces` | 9/9 |
| `quotation_flow_inline_customer.py` | Quotation create with inline customer quick-add | 8/8 |
| `quotation_crud_lifecycle.py` | Quotation update / edit-guard / send / reject / cancel (+guards) | 7/7 |
| `sales_order_crud_lifecycle.py` | SO create / update / confirm / edit-guard / cancel | 6/6 |
| `delivery_receipt_crud_lifecycle.py` | DR CRUD + lifecycle; **DR-edit bug tripwire** | 9/9 |
| `full_sales_area_as_ca.py` | Full O2C spine as CA; SI blocked (role-independent) | 10/10 |
| `action_items_and_audit_log.py` | Action Items badge + Audit Log trail | 12/12 |
| `chief_accountant_role_crud.py` | CA master-data + Sales CRUD; account self-approve | 9/9 |
| `staff_sales_area_sod.py` | Staff: module-gated, write ✓, **approve ✗** | 12/12 |
| `accountant_sales_area_sod.py` | Accountant: module-gated, write ✓, **approve ✓** | 8/8 |
| `ca_registers_and_edits_perms.py` | CA registers accountant+staff; edits staff perms, **not** accountant's | 10/10 |

**Role matrix:** admin/CA → gate bypassed, write ✓, approve ✓ · accountant → gated, write ✓,
approve ✓ · staff → gated, write ✓, approve ✗.

---

## Open findings feeding the plan (see memory `project-bug-tracker` + `docs/bug-reports/`)

- 🔴 **BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS** (HIGH) — **gates all of Tier 2.** Posting engines
  resolve AR/AP/WHT by hardcoded magic codes; a self-built COA can't post SI/CR/AP/CDV.
- 🔴 **BUG-DR-EDIT-FALSE-CONFLICT** (HIGH) — draft DR edit always false-conflicts (csrf-only form
  drops `row_version`); pinned as a tripwire in `delivery_receipt_crud_lifecycle.py` (flip when fixed).
- 🔵 **Rule-#9 candidate** — SO Print button vs `so_print_form=hidden` (see T1.1); confirm before backfilling.
- 🔵 Other UX/feature (non-blocking): `BUG-SETTINGS-NEEDS-TABS`, `BUG-CA-ACCESS-GRID-POINTLESS`,
  `BUG-DR-DETAIL-GRID-UNSTYLED`, `BUG-DASHBOARD-ASOF-DEFAULT-EOM`, `FEAT-IS-BY-PRODUCT-LINE`.
- 🟢 Fixed-in-tree: `BUG-SIDEBAR-QUOTATIONS-ORDER` (Quotations first).

## Out of scope beyond this run (parked — don't forget)

Multi-branch flows; Credit/Debit memo deep-dive; Year-End Close; Opening Balances; viewer role;
concurrency/lost-update stress; deploy/backup paths.
