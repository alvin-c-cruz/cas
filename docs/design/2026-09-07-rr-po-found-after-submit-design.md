# A purchase order turns up for a receipt that was recorded without one

**Date:** 2026-09-07
**Status:** design agreed, not yet implemented
**Area:** receiving reports, purchase orders
**Follows:** `rrdirect_0001` (PO-less receiving reports)

---

## The situation

PO-less receiving reports let a receipt record goods that arrived with no purchase
order — a walk-in purchase, a replacement part, a sample. Then somebody finds the
purchase order that covered them after all, and the receipt has already been submitted.

## What happens today, and why it is worse than a missing link

A receiving report can only be edited while it is `draft`. There is no unsubmit and no
return-to-draft, so once submitted the only exits are approve or cancel. The link cannot
simply be attached.

Four things are wrong while the mismatch stands:

- **The order still reads as fully open.** `po_line_open_qty` counts only receipt lines
  carrying a `purchase_order_item_id`. The same goods can therefore be received *again*
  against that order, with no warning. This is a genuine double-receipt exposure, not a
  cosmetic defect.
- **The requisition chain never learns.** `_refresh_source_requisitions` walks receipt
  lines back through the order to the requisition. A direct line reaches nothing, so a
  requisition stays "Ordered" forever despite having been delivered.
- **If approved, it is valued wrong.** A direct line posts at `Product.standard_cost`;
  the order line carries the real agreed price. Inventory and GRNI are both out by the
  difference.
- **Billing loses its price check.** The accounts-payable variance logic keys off the
  receipt line's order line. Without one there is nothing to compare the vendor's
  invoice against.

## Scope, as decided

| Question | Decision |
|---|---|
| Which states must be repairable? | `submitted` only — before approval, nothing posted |
| How often will this happen? | Weekly or more, so prevention leads and repair backs it up |
| How hard should the system push back? | Warn, override allowed **with a recorded reason** |
| When does the receiver meet the warning? | At pick time, in the modal — not as a save-time refusal |

Approved (stock posted, GRNI accrued at standard cost) and billed (an AP voucher
exists) are **out of scope**. Both are recoverable today by cancelling, which reverses
the stock, except billed — which cannot be cancelled at all. If either turns out to
happen in practice, it is a separate design.

---

## Part 1 — Prevention

### Detection costs one field

`_po_lines_payload` rows gain `product_id`. Nothing else is needed, because that helper
feeds both places open order lines are published: the server-rendered payload on the
edit page, and the `/receiving-reports/open-lines?vendor_id=` endpoint the create page
calls once a vendor is chosen. One field, both paths, no new query and nothing to keep
in sync.

The warning reads the **endpoint**, not the page-load payload. On a fresh create page
`eligible` is deliberately empty — there is no vendor until the receiver picks one — so
a page-load payload would be blank exactly when the warning is most needed. Opening
**Add Item Without PO** therefore fetches the current vendor's open lines, and builds an
index of `product_id → [{po_number, open, purchase_order_item_id}]` from the response.

Fetching at that moment rather than at page load has a second benefit: the index is
always current, which narrows (though does not close) the gap where an order is approved
between picking and saving.

### What the receiver sees

```
Add Item Without PO
  Product: [RM0863 — TQC BREAKER            ▾]

  ⚠ This vendor has 10 open on PO-00985.
     ( ) Receive against PO-00985
     (•) It really had no PO — why?
         [ Free replacement for the damaged unit ]

  Unit:  [ Use the product's default ▾ ]
  Qty:   [    ]
              [ Add to receipt ]  [ Cancel ]
```

*Receive against PO-00985* closes the modal and adds the order-backed line through the
existing path — same ceiling check, same guards. No direct line is created.

The override requires its reason before **Add to receipt** enables.

### Why it warns rather than blocks

The match is a heuristic. It knows only that this vendor has an open order line for this
product; it cannot know whether this particular carton came off that order. A free
replacement, a sample, or a second delivery from the same vendor are all legitimate
direct receipts against an open order. Blocking would make them unrecordable.

### Where the reason lives

A nullable `no_po_reason` on `receiving_report_items`, and the same text in the audit
log. **Per line, not per receipt:** the judgement is about one item, and one receipt can
hold several with different answers.

Set only when the warning actually fired. A direct line for a product with no matching
open order has nothing to explain, and a reason on it would be noise.

---

## Part 2 — Repair

### Return to Draft, on a submitted receiving report

`POST /receiving-reports/<id>/return-to-draft`, mirroring the purchase-requisition
route added in `prreturn_0001`.

**Who** — an approver (`has_full_access or role == 'accountant'`) **or the person who
submitted it** (`rr.submitted_by_id == current_user.id`). The approver rule matches
`cancel()` on this same document; the submitter rule was an explicit owner decision, on
the grounds that pulling back your own submission is not an act needing someone else's
authority. It fails closed: a legacy receipt with a NULL `submitted_by_id` falls back to
approver-only.

**From what** — `submitted` only. A receiving report has no `rejected` status, so unlike
the requisition there is exactly one source state.

**Memo** — required, minimum 10 characters, matching `reject`/`cancel` and the
requisition equivalent. Stored on the receipt and written to the audit log as
`Returned to draft from submitted: <reason>`.

**Then nothing new happens.** The receipt is draft, so the ordinary edit form opens:
remove the direct line with its `×`, pull the real one via **+ Pull from Purchase
Orders**, save, submit. The ceiling check, the vendor/branch/status guard and the
line-identity rules all already apply, because it is the ordinary edit path.

**On re-submit the memo is cleared**, along with `returned_by_id` and `returned_at` —
the same correction applied to purchase requisitions in fa78173a (2026-09-06). A memo describes one
correction cycle; submitting starts the next. Without this, a receipt that goes back and
forth accumulates stale notices describing decisions already acted on.

### It deliberately does not auto-link

A repair that silently re-pointed the line would be the system asserting something only
a human can know. The receiver chooses the order line through the picker, as they would
have originally.

### Making the backlog findable

The receipt list gains a marker for receipts carrying direct lines. At weekly frequency
these need to be reviewable without opening each one — and it is the same view that
shows whether the prevention above is working.

---

## Schema

One migration, two tables, four columns. All nullable, all additive, nothing to
backfill: every existing row reads NULL and behaves exactly as it does today.

```
receiving_report_items
  no_po_reason         TEXT       why this was not received against the matched order

receiving_reports
  return_reason        TEXT       why it was sent back to draft
  returned_by_id       INTEGER    who sent it back
  returned_at          DATETIME   when
```

`returned_by_id` is declared as a **plain Integer in the migration, with
`db.ForeignKey` on the ORM side only**. A SQLite batch `add_column` cannot carry an
inline foreign key — the table rebuild raises "Constraint must have a name". This is the
same arrangement `prreturn_0001` used, and the reason `receiving_report_items` shows
three foreign keys in the live database rather than five.

**A third migration in this area, not folded into `rruom_0001`.** Folding was considered
and rejected on the owner's call (2026-09-07): `rruom_0001` carries the unit column for
direct receipts, and folding would have held that work back behind this design. It
shipped instead in `3325c58b`, so `unit_of_measure_id` is no longer part of this
change. The cost is one further upgrade on each client instance — five of them, two
already behind — accepted deliberately in exchange for unblocking work that was ready.

**Verified against a copy of the live Philgen database**, never a `create_all()` test
database — the latter builds its schema from the models and cannot reproduce the real
one's constraint naming. Confirm after upgrade: three foreign keys, both indexes, every
row, clean `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.

---

## Failure modes and edge cases

**The vendor changes after lines are added.** The form already clears the grid and shows
a notice. The warning index is rebuilt from the new vendor's orders, so a stale match
cannot survive the change.

**The matched order line has less open than arrived.** Choosing *Receive against
PO-00985* goes through the ordinary picker, so the existing ceiling refuses the excess
and names the line. The receiver can take what fits against the order and record the
remainder as a direct line — which is what an over-delivery actually is.

**Several open orders match one product.** The warning lists each with its own open
quantity. The receiver chooses; the system does not guess.

**The receipt is returned to draft and simply re-submitted unchanged.** Legitimate — the
memo records that someone looked. Nothing is enforced beyond the memo.

**A direct line is removed during repair but the order line is not pulled.** The receipt
saves with fewer lines, or is refused entirely if it would be left empty ("Add at least
one received line"). No half-written state: the whole payload is validated before the
first line is built.

**Two returns in a row.** The second memo replaces the first. Both survive in the audit
log, which is the permanent record; the column holds only the current cycle.

---

## Known limits, stated rather than hidden

**The warning is not enforcement.** Pick-time warning was chosen over a save-time
refusal, so the server stores the reason but does not refuse a line lacking one. Two
ways past it: a raw POST, and an order approved between picking and saving. This is a
deliberate trade for lower friction on a weekly event, recorded here and in the code
comment so it is not mistaken for an oversight. The list marker above is what makes such
cases findable if it ever matters.

**Approved and billed receipts are not repairable.** Out of scope by decision. A billed
receipt cannot even be cancelled today.

**Detection is per vendor and product.** It cannot see that a delivery matches an order
placed with a different vendor, or a product recorded under a different code.

---

## Testing

Mirroring `test_rr_direct_receipt.py`, which this extends.

**Prevention**
- the payload carries `product_id` — without it no match is possible
- a direct line for a product with an open order line for that vendor is flagged
- CONTROL: a product with no open order line is not flagged, and a product whose open
  line belongs to a *different* vendor is not flagged
- the override reason is stored on the line and reaches the audit log
- a direct line with no matching order stores no reason

**Repair**
- an approver can return a submitted receipt to draft; so can its submitter
- CONTROL: an unrelated staff user cannot, and a NULL `submitted_by_id` falls back to
  approver-only
- a memo under 10 characters is refused
- draft, approved, billed and cancelled receipts are all refused
- the memo, who and when are stored and audit-logged
- re-submitting clears all three
- CONTROL: the audit log still holds the memo after the clear — which is what makes
  clearing safe rather than destructive

**Schema**
- every new column is nullable, and a row with all of them NULL behaves as it does today
- the migration round-trips on a copy of the live database

Every refusal test to be mutation-checked by removing the guard and confirming it fails.
