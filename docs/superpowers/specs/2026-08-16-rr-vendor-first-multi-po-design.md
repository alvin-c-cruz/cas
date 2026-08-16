# Receiving Report — vendor-first form, receiving across several POs

**Date:** 2026-08-16
**Module:** `receiving_reports` (touches `purchase_orders`, `purchase_billing`, `company_settings`)
**Owner decisions recorded:** 2026-08-16 (three of them, marked ★ below)

## The gap

Verified against `main` at `47eacefa`, not taken from recollection.

The Receiving Report form does not follow the shape of its siblings, and it cannot express what
actually happens on the receiving dock.

| | Purchase Order | Accounts Payable | **Receiving Report** |
|---|---|---|---|
| First choice | **Vendor** (Choices picker) | **Vendor** | **a single Purchase Order** |
| Bulk-add | `+ Pull from Requisitions` | `+ Pull` (vendor-scoped) | none — the PO's lines appear |
| Line grid | product / desc / qty / uom / price | per-line, editable | received-qty only |
| Header keys | `vendor_id` | `vendor_id` | `purchase_order_id` **`nullable=False`** |

Two consequences:

1. **A delivery that settles two POs cannot be recorded as one receipt.** The receiver must split it
   into two RRs against one physical delivery, or not record it faithfully.
2. **Vendor is derived, not chosen.** `ReceivingReport.vendor_id` already exists but is a snapshot
   copied off the PO — the model comment says so verbatim: *"Vendor snapshot (from the PO at create;
   no picker)."*

## Decisions

| Question | Decision |
|---|---|
| ★ Can one RR span several POs? | **Yes — of ONE vendor.** A delivery settles what the vendor sent, which may cover more than one order. |
| ★ What happens to `purchase_order_id`? | **Dropped.** The PO(s) are derived through each line's `purchase_order_item`. `vendor_id` becomes the header key at `nullable=False`. |
| ★ Pre-printed `po_number` | **Moves from a header field to a per-line column.** A multi-PO RR has no single PO number, and a blank box on pre-printed stationery reads as a system failure. |
| Cross-vendor lines | **Refused.** One RR, one vendor — enforced at save, not only by the picker. |
| Where the ceiling is enforced | **At save AND at approve, aggregated per PO line** (see Invariants). |

## The model change — this is what the ★ approval covers

```
receiving_reports
  - purchase_order_id   Integer FK(purchase_orders.id)  nullable=False  index   <-- DROP
    vendor_id           Integer FK(vendors.id)          nullable=True   index   --> nullable=FALSE
    vendor_name         String(200)                     nullable=False          (unchanged, snapshot)

receiving_report_items
    purchase_order_item_id  Integer FK  nullable=False   (UNCHANGED — this already carries the truth)
```

**Migration** (hand-written, `op.batch_alter_table` — `Migrate()` runs without `render_as_batch`):

1. Backfill `vendor_id` from the header PO where NULL, **before** tightening it. Every existing row
   has exactly one PO, so this is total.
2. Alter `vendor_id` → `nullable=False`.
3. Drop `purchase_order_id`.

No data is lost: the PO of every existing RR remains reachable through its lines'
`purchase_order_item_id`, which is `nullable=False` and therefore always present.

**Verify on a copy of a real client DB**, not on a `create_all()` fixture — batch mode reflects the
existing schema and silently preserves old constraints. PhilGen's backup is the realistic target
(it has RRs); `philgen.db` locally is the working copy.

## The form

Mirror the PO form, because that is the convention the owner named:

```
Vendor:   [ Metro Fastener & Hardware Supply Corp  ▾ ]     <- Choices picker, FIRST
RR #:     [ 00042 ]        Receipt date: [ 2026-08-16 ]
Remarks:  [ ................................................ ]

[ + Pull from Purchase Orders ]        <- scoped to the selected vendor

  #  Product        From PO     Description      Ordered  Received  UOM
  1  Hex Bolt       PO-00042    SS304, box 100      20       [20]   BOX
  2  Angle Bar      PO-00051    6m mild steel       60       [60]   PCS
```

- The Pull picker lists **open lines of the selected vendor's receivable POs**, exactly as PO's
  picker lists open requisition lines. `_eligible_purchase_orders(branch_id)` becomes
  `_eligible_purchase_orders(branch_id, vendor_id)`.
- **Changing the vendor after lines exist must not silently orphan them.** Either block the change
  or clear the grid with a visible warning — decide during implementation, but it must not be
  silent.
- Follow the PO picker's two behaviours fixed on 2026-08-16: re-pulling **merges** into the existing
  row rather than stacking a duplicate, and a pull **consumes** the seeded blank row.

## Derivation rules (what replaces the dropped column)

| Surface | Today | After |
|---|---|---|
| `detail.html:29` | `rr.purchase_order.po_number` link | the distinct POs across `rr.line_items`, each linked |
| `list.html:80` | one PO number | one PO number when unambiguous, else a count (e.g. "2 POs") |
| `print.html:30` | `PO #: …` header line | per-line column |
| `print_preprinted.html:122` | `po_number` header field | `po_number` **column** |
| `preprinted_layout.py` | `FIELD_KEYS` has `po_number` | move it into `COLUMN_KEYS` |
| **`purchase_billing.py:122`** | `ReceivingReport.purchase_order_id == po.id` | **join through the lines** |

`purchase_billing.py` is the one that is not cosmetic. It decides whether a PO is billed **directly**
or **via its RR**. If it keeps filtering on a dropped/NULL header column, a received PO looks
unreceived and becomes directly billable *while also* billable through its RR — a double-bill route.
It must be rewritten in the same change, not after.

**The pre-printed layout is free to change right now and will not be later.** `rr_preprinted_layout`
shipped on 2026-08-16 and has never been deployed, so no client has a saved layout keyed on its
current `FIELD_KEYS`/`COLUMN_KEYS`. Once one does, changing those keys silently breaks their
stationery alignment.

## Invariants — and a live bug this work must not inherit

**1. One vendor per RR.** Every line's `purchase_order_item.purchase_order.vendor_id` must equal the
header `vendor_id`. Enforced at save. A picker filter is not enforcement — a raw POST bypasses it.

**2. Branch scope.** Every pulled PO must belong to the session branch, as today.

**3. The receipt ceiling must be aggregated per PO line — this is currently BROKEN, before any of
this work.** Verified on `main`:

- `_parse_rr_lines` (`views.py:118`) appends **one `ReceivingReportItem` per payload entry** with no
  dedupe, so two entries naming the same `purchase_order_item_id` create two RR lines for one PO line.
- The approve guard (`views.py:360`) then checks **per line**:
  `po_line_open_qty(li.purchase_order_item, exclude_rr_id=rr.id)`. Because the exclusion drops the
  whole RR, two lines of 10 against an open 10 each pass on their own — 20 received against 10
  ordered.
- Note `_submitted_receipts` (`views.py:95`) *does* collapse by `poi_id` into a dict, which is why
  the current single-PO UI never produces this. That collapse is incidental protection from a
  display helper, not a guard — and the new multi-PO grid must not be built on the assumption that
  it holds.

This is the **same defect class** as `BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION`
(PO/PR, fixed 2026-08-16, cas `66bf733f`): a per-item check whose ceiling is read from the database
and therefore cannot see the siblings in its own payload. Sum per `purchase_order_item_id` across
the whole payload, then check each PO line **once**, at save and at approve. Reuse the shape of
`assert_payload_within_open_qty`.

**4. Over-receipt remains refused, but the message must name all contributing lines**, as the PO fix
now does (*"Lines 1, 2: only 1.0000 of COAL remain unordered, but these lines order 2.00 between
them"*).

## Verification

- **Render assertions on the GET**, never a POST-contract test — a test that posts a payload it
  built itself cannot see a field the template failed to render.
- **Controls that would fail a naive fix:** two lines from *different* PO lines of the same vendor
  must SUCCEED; two lines summing to *exactly* the open quantity must SUCCEED. A receiver splitting
  one PO line across two delivery dates is legitimate.
- **Cross-vendor refusal tested at the route**, not only by the absence of a picker option.
- **The billing path tested both ways**: a PO with an approved RR is billed via the RR and is NOT
  offered for direct billing; a PO without one still is. This is the regression that would otherwise
  reach the ledger.
- **Migration verified on a copy of PhilGen's real backup** — assert the RRs' POs are still
  reachable through their lines afterwards.
- **Blocking pre-merge `/ui-test philgen --branch <name>`**: templates and JS change, and the Choices
  pickers plus received quantities are exactly what a DOM-shim harness cannot see. Drive one delivery
  spanning two POs of one vendor, end to end.
- `app/receiving_reports/*` and `app/purchase_billing.py` are `regression-map.json` keys; the
  `receiving_reports` marker was repaired on 2026-08-16 and now selects 218 tests, so the mandated
  marker run is real evidence again rather than a no-op.

## Out of scope

- The AP form itself — it is the reference, not the subject.
- RR list/detail redesign beyond what the dropped column forces.
- Partial-receipt workflow changes, over-receipt tolerance, and lot/serial capture.
- Any change to `purchase_order_item_id` on the line: it stays `nullable=False` and remains the
  single source of the PO link.
