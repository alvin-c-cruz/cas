# BUG-PRODUCT-MASTER-DUPLICATE-CREATE + BUG-PRODUCT-FORM-TRACK-INVENTORY-DEFAULT

**Severity:** Low–Medium (no data loss; silent duplicate master records, and one form field that
misreports a stored value)
**Status:** RESOLVED 2026-09-25 (section-by-section below). Nothing changed in the live database.

> **Resolution, 2026-09-25**
>
> 1. **Duplicate product — FIXED** in `47062064`. The mechanism was simpler than the guess in
>    §1: there was no duplicate check anywhere, and the quick-add and the full form post to the
>    SAME route, so the `code` NULL inference pointed nowhere (the code field is retired and
>    every product since `prodcode_0001` has it NULL). `ProductForm.validate_name` now refuses
>    a name another product has (case/whitespace-insensitive, active or inactive); owner chose
>    block, no override. The existing twins (615/617 here, two pairs in the local copy) stay
>    editable because the check runs only when a name changes. 615 is still unreferenced and
>    can be deleted through the app.
> 2. **track_inventory "y" — NOT A BUG.** WTForms renders every checkbox with the constant
>    submit value `value="y"`; whether it is ticked is the separate `checked` attribute, which
>    follows the stored value (verified: stored 0 renders unchecked, stored 1 renders
>    `checked`). §2 read `input.value`. Pinned by
>    `tests/integration/test_product_track_inventory_renders_stored_value.py`.
> 3. **AP edit unlinks PO/RR — FIXED and deployed 2026-09-22** (`c7b3c373`): AP edit refuses a
>    payee change while a PO/RR is still billed to it; PO 01134 was repaired.
**Discovered:** 2026-09-23, reviewing 22 Sep activity in `philgenbooks2023` for the daily report.
**Raised by:** Alvin Cruz, via the bookkeeping workspace
**Affects:** `products` master — create form, edit form

---

## 1. The product master accepts a byte-identical duplicate with no warning

On 22 Sep 2026 the same user created the same product twice, 55 minutes apart, and the app
accepted both without comment.

| | id 615 | id 617 |
|---|---|---|
| `name` | `EPSON LQ-310 DOT MATRIX PRINTER` | `EPSON LQ-310 DOT MATRIX PRINTER` |
| `created_at` | 2026-09-22 14:07:54.607733 | 2026-09-22 15:02:22.544627 |
| `created_by_id` | 2 | 2 |

All **seventeen** columns were compared, not just the ones the edit form renders. Only `id` and
`created_at` differ. Everything else is identical and, in both cases, empty: `code`,
`description`, `default_unit_of_measure_id`, `default_unit_price`, `default_account_id`,
`category_id`, `job_order_name`, `standard_cost`, `costing_method`, `reorder_level`,
`customer_code` are all NULL; `is_active` = 1 and `track_inventory` = 0 on both.
`product_allowed_units` has no rows for either.

### Why it matters

Purchase history splits across two ids for what is one item. Here **617 is referenced by purchase
requisition 00996 and 615 is referenced by nothing at all** — no requisition, purchase order,
receiving report, AP voucher or sales order — so this instance is cheap to clean up. The next one
may not be, if both ids get used before anyone notices. A product master is a long-lived lookup;
divergence is silent and only shows up later as a split spend history or a reorder level that
never triggers.

The same pattern is visible elsewhere in the table, so this is not a one-off: `products` currently
holds 618 rows and many carry `code` = NULL, which suggests they arrive through the inline
quick-add rather than the maintained master.

### Suggested handling

A hard uniqueness constraint may be wrong — two genuinely different items can share a
manufacturer's description. A **warning on save when a case-insensitive, whitespace-normalised
`name` already exists**, offering "use the existing one" against "create anyway", would catch this
without blocking legitimate cases. Worth applying to the **inline quick-add** too (the
`__add_product__` path in the PR/PO line pickers), which is where a user is least likely to check
the master first.

---

## 2. The edit form shows `track_inventory` as "y" when the stored value is 0

On `/products/<id>/edit` the `track_inventory` control reads **`y`** for both 615 and 617, while
the stored column is **`0`** on both.

Reading the form, I reported to the owner that both products tracked inventory. They do not. The
form is showing a default rather than the persisted value, so the page misstates the record.

This is the more dangerous of the two findings, because it is not a nuisance but a **wrong
reading**: anyone checking a product's configuration through the UI gets an answer the database
does not support, and saving the form unchanged would presumably write the displayed default back,
silently flipping the flag on.

### Suggested handling

Bind the control to the stored value, and treat a NULL/0 as off rather than falling through to the
form default. Worth checking whether the same default-over-value pattern affects the other
tri-state or boolean fields on this form (`is_active`, `costing_method`).

---

## Reproduction

1. Create a product from the master, or from the inline quick-add on a purchase requisition line,
   giving only a name.
2. Repeat with exactly the same name. Both are accepted; no warning, no link between them.
3. Open either one at `/products/<id>/edit` and compare `track_inventory` on screen with the
   `products.track_inventory` column.

Verified against the live snapshot `philgen-20260923-0641.db`, pulled 23 Sep 2026 06:41 via the
PythonAnywhere Files API.

---

## 3. Editing an AP voucher silently unlinks it from its PO and RR

**Severity: Medium.** This one destroys a real relationship rather than just annoying a user.

An AP voucher line created with **Pull** from a receiving report stores `source_po_item_id` and
`source_rr_item_id`. **Any subsequent save of the edit form wipes both back to NULL**, because the
form posts `source_rr_ids` as `[]` — that hidden field is populated by the Pull action and is empty
on a normal page load, so re-saving looks like "no sources selected".

Reproduced three times on APV 00020 (Rubix Tyre & Battery Center, 23 Sep 2026):

| Action | `source_po_item_id` / `source_rr_item_id` after save |
|---|---|
| Pull from RR 00750, set account, Update | 41 / 42 |
| Reopen, change the expense account, Update | **NULL / NULL** |
| Re-pull, set account, Update | 41 / 42 |
| Reopen, edit the **Notes** text only, Update | **NULL / NULL** |

Editing a free-text note should not be able to sever a document's link to its purchase order.

### Why it matters

The link is what lets a receiving report ever be reported as billed. An unlinked voucher leaves the
RR showing as outstanding forever, which is exactly the "every approved RR should end with an AP
voucher" check the owner asked to monitor. It is also silent: the voucher totals, VAT and
withholding are all still correct, so nothing on screen suggests anything was lost.

The current workaround is ugly: **delete the line, Pull again, set the account, and Update in one
pass, without reloading the page between the pull and the save.** Any later edit repeats the damage.

### Suggested handling

On the edit form, when `source_rr_ids` is absent from the POST, leave the existing per-line
`source_po_item_id` / `source_rr_item_id` untouched rather than clearing them. An empty hidden
field means "the user did not run Pull this time", not "the user removed the sources".
