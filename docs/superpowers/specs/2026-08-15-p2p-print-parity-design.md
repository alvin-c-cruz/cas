# P2P Print Parity — Design

**Closes the print surface of:** `BUG-P2P-LIST-DETAIL-VOUCHER-UX-PARITY-GAP` (Medium, open since
2026-07-23) — 1 of 4 surfaces (list) shipped 2026-07-23 as `482c4178`; this spec covers **print**.
Detail and form remain open as their own sub-projects.

**Date:** 2026-08-15
**Modules:** `purchase_requests`, `purchase_orders`, `receiving_reports`

## The gap

Verified against `main` on 2026-08-15, not taken from the (3-week-old) bug entry:

| Module | list.html | detail badge | print.html | list_print.html | print_preprinted.html |
|---|---|---|---|---|---|
| purchase_requests | shipped | missing | **283 lines, branded — DONE** | absent | absent |
| purchase_orders | shipped | missing | 57 lines, bare | absent | absent |
| receiving_reports | shipped | missing | 52 lines, bare | absent | absent |
| accounts_payable (reference) | — | present | 245 lines, branded | present | present |

**Correction to the bug entry.** It states PO's bare shape applies "by extension to PR/RR". That is
**no longer true of PR**: `purchase_requests/print.html` is now 283 lines — larger than AP's — with a
company letterhead (`company_logo` + name/address/TIN), explicit `@page` sizing, print media queries
and an inline signatory editor. It was refined as recently as `956ea554` ("restructure the printed
requisition's header and line columns"). **PR's plain print needs no work**; only PO and RR do.

This also changes the reference template. PO and RR should mirror **PR's own print.html**, not AP's:
it is the same document family, it already solves the letterhead and signatory-editor problems for
these documents, and it is the shape the owner most recently shaped by hand. Copying AP would import
a voucher layout designed around posting/VAT concerns these documents do not have.

Two distinct problems, not one:

1. **PO's and RR's plain print is not a client-facing document.** `purchase_orders/print.html` is 57
   lines of unstyled table with `window.print()`/`window.close()` buttons and no letterhead; RR's is
   52. Both read as debug dumps rather than documents.
2. **A real missing feature:** PR/PO/RR were never wired into the pre-printed layout designer.
   `apv`, `cdv`, `crv`, `dr`, `jv`, `payslip`, `so`, `sv` all have it; the P2P trio does not. A
   client cannot print any P2P document onto their actual pre-printed stationery.

`list_print.html` (a printable filtered list) is also absent from all three.

## Decisions

| Question | Decision |
|---|---|
| Which surface first | **Print.** It is the only one of the three remaining surfaces containing a missing FEATURE rather than styling drift, and the PO is the one P2P document that leaves the company. |
| How to add the designer | **Shared base, for the 3 new modules only.** |
| Which modules get pre-printed | **All three.** Full parity with the existing eight. |
| VAT/WHT ladder | **Out of scope** — it is a form question, deferred to the form sub-project. |
| Print-button gating | **Added**, matching the other families' `*_print_access` convention. |

## Architecture — one core, three thin declarations

The existing system is eight near-identical clones **on both sides**:

- `app/*/preprinted_layout.py` — 2265 lines over 8 files. Normalising document names, SO vs SI
  differ by **76 lines**: ~75% is shared boilerplate (canvas, fonts, clamps, sanitisation).
- `app/static/js/*_preprinted_designer.js` — 3434 lines over 8 files. Same normalisation, SO vs SV
  differ by **19 lines** — ~96% identical.

Cloning three more would add ~850 lines of Python and ~1300 of JavaScript that is almost entirely
copy.

**New shared core:**

- `app/common/preprinted_base.py` — the 912×1008 canvas at 96dpi, `SAFE_MARGIN`, `FONT_GROUPS` and
  `ALLOWED_FONTS`, the font/width/row clamps, paper sizes and date formats, the `MAX_EXTRAS` cap,
  the three signatory text blocks, and the sanitise-on-read-and-write logic.
- `app/static/js/preprinted_designer.js` — the designer core, parameterised by a config object each
  page supplies (its fields, columns, and save endpoint).

**Per module, `preprinted_layout.py` shrinks to ~40 lines:** its `LAYOUT_SETTING_KEY`, `FIELD_KEYS`,
`FIELD_LABELS`, `COLUMN_KEYS`, `COLUMN_LABELS`. Nothing else.

**The eight existing layouts are NOT touched.** They are client-facing and their alignment on real
pre-printed stationery is pixel-sensitive; rewriting them buys no user-visible value and would need
a browser pass each. If the base proves itself here it becomes their migration target later — a
separate decision, not this arc's.

## What each layout declares

**Purchase Order** (`po_preprinted_layout`) — closest to SO; the document a supplier receives:

- Fields: `po_no, order_date, expected_date, vendor_name, vendor_tin, vendor_address,
  payment_terms, reference, vat_treatment, total_amount`
- Columns: `line_number, product, description, quantity, uom, unit_price, amount`

**Purchase Requisition** (`pr_preprinted_layout`) — internal; no vendor, no money:

- Fields: `pr_number, request_date, date_needed, reason, branch`
- Columns: `line_number, product, description, quantity, uom`
- `date_needed` renders **"ASAP"** when `date_needed_asap` is set. The model stores the two as
  mutually exclusive (setting one clears the other), so the layout must never print both.

**Receiving Report** (`rr_preprinted_layout`) — receipt evidence; references its PO:

- Fields: `rr_number, receipt_date, vendor_name, po_number, remarks`
- Columns: `line_number, product, description, ordered_qty, received_quantity, uom`

**Only three of those columns are stored on the RR line.** `ReceivingReportItem` carries
`line_number`, a `product_id` snapshot and `received_quantity` — nothing else. `description`,
`ordered_qty` and `uom` are **derived through `purchase_order_item`**, the FK to the PO line being
received, exactly as the model's own comment states: *"A RR line's quantity is the RECEIVED
quantity; UoM/price belong to the PO line it receives."* That FK is `nullable=False`, so the
relationship is always present and the derivation is safe. The layout must read them through it
rather than expecting columns that do not exist.

**Two deliberate omissions**, recorded so they are not later read as oversights:

- **PR carries no amounts at all** — no unit price, no total. A requisition asks for goods, not
  spend; pricing arrives at PO. (This matches `PurchaseRequestItem`, which has no price column.)
- **No VAT/WHT ladder anywhere in this arc.** PR and RR have no VAT in their data model, and PO's
  VAT is a header-level `vat_treatment`, not AP's per-line ladder. That is a form-surface question.

Each layout inherits the base's shared furniture: Preparer/Checker/Approver text blocks, paper
choice (continuous or letter), date formats, and the duplicated-field cap.

## The plain print surfaces

**`print.html` for PO and RR only** — PR's is already done (see Correction above) and is the model
to follow: company letterhead with `company_logo` and name/address/TIN, explicit `@page` sizing,
print media queries, and the inline signatory editor gated on `can_edit_signatories`.

Bringing PO and RR up to that shape means each gains a letterhead and a **signatory block** —
Prepared / Checked / Approved — which a supplier-facing PO and a signed goods-received document both
genuinely need. Extract PR's letterhead and signatory-editor markup into a shared partial as part of
this, so the three stay in step rather than drifting again; PR's own template is refactored to use
the partial without changing what it renders.

**`list_print.html` per module** — a printable version of the list that must print **the filtered,
paginated result the user is looking at**, reusing the same query the list page just ran. Printing
an unfiltered dump is the plausible failure and the reason this surface exists.

**`*_print_form` setting** — `pr_print_form`, `po_print_form`, `rr_print_form`; each `current` or
`preprinted`; the print route renders accordingly. Mirrors the existing eight.

**Gating — corrected from the design discussion.** I said there that the other families gate the
Print button behind a `*_print_access` setting and that PR/PO/RR should match "for consistency".
That premise was wrong: `*_print_access` exists on the six **posting** vouchers (`apv`, `cd`,
`cd_check`, `cr`, `sv`, `payslip`) where "do not print an unposted voucher" is the concern, and
**SO, DR and JV — the closest analogues to these documents — have none.** Consistency argues
against adding it.

So:

- **All three use `*_print_form` with three values**, exactly as SO does: `current` (standard
  printable form), `preprinted` (data-only overlay for the client's stationery), and `hidden`
  (printing disabled). `hidden` is the off switch; no second setting is needed for it.
- **PO additionally gets `po_print_access`**, on its own merits rather than for consistency: the PO
  is the one P2P document that leaves the company, and a *draft* PO sent to a supplier is a real
  commercial problem. Default `approved_only`. PR and RR are internal and need no equivalent.

Wherever a gate exists, two requirements hold: the button is shown when allowed and **hidden when
not**, and a **direct GET of the print URL respects the same gate**. A hidden button is not access
control.

**Jargon consistency:** list, detail, form and print must all use the same name for the document.

## Verification

**Mockup first.** Both new surfaces (branded print, designer canvas) are UI-bearing, so each gets a
self-contained static HTML mockup with dummy data, reviewed in a browser and **approved before any
Jinja is written**. Placement is cheap to change in a mockup and expensive once three modules render
it.

**The shared base carries the highest test weight** — a defect there breaks all three modules at
once. Its sanitiser is tested to prove that stored or POSTed JSON cannot inject unknown keys, push a
number out of range, or select an unlisted font; and that **a layout saved before a field existed
still renders that field at its default**. That last case is what silently breaks a client's saved
stationery alignment after an upgrade.

**Print gating tested in both directions** — visible when allowed, absent when not — and separately
at the route, with a direct GET refused under the same rule.

**Render-assertions on the GET, never a POST-contract test.** A test that posts a payload it built
itself cannot see a field the template failed to render; that is precisely how
`BUG-DR-EDIT-FALSE-CONFLICT` shipped green in this codebase.

**Controls:**
- Each module keeps its own document identity — a test that would still pass if PR's layout rendered
  PO's fields is not a test.
- `list_print.html` is asserted against a **filtered** list, not an empty or unfiltered one.

**Gates before merge:** full suite; marker-selected dependents for any `regression-map.json` key
touched (by marker, never a `-k` sweep); and the `/ui-test <slug> --branch` browser pass, which is
**blocking** — this arc is almost entirely templates and JS, so pytest evidence alone cannot merge
it. New JS carries a `?v=N` cache-buster on every template that loads it.

## Out of scope

- **Detail surface** (status badge colouring, audit-trail lines) — its own sub-project.
- **Form surface** (Choices.js pickers, inline quick-add, the VAT/WHT ladder question) — its own
  sub-project, and the one carrying the open design decision.
- **Migrating the existing 8 layouts onto the shared base** — deliberate; see Architecture.
