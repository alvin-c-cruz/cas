# Voided AP Bills in AP Journal & List — Design Spec

**Date:** 2026-06-14

## Problem

Voided AP bills are currently invisible in the AP Journal. When a draft bill is voided, its linked JournalEntry is deleted (no posting ever occurred), so the JE-based AP Journal query returns nothing for that bill. The bill number is consumed in the sequence but the record disappears from the journal view — a gap that makes the journal non-auditable.

The AP List already shows voided bills (no status filter excludes them by default), but template styling (badge + strikethrough) needs to be confirmed.

## Rules Established

- Voided records **are included** in the document number sequence. Numbers are never reused.
- Voided records **must appear** in the AP Journal and AP List by default (no toggle required).
- Financial statements are unaffected: voided bills are always drafts, so no JE ever posted to the books.

## Chosen Approach

**Option A — extend `build_columnar` with a `voided_bills` third row type**, mirroring the existing `draft_entries` pattern. The view fetches voided `PurchaseBill` rows within the period and passes them directly; no JE exists or is needed.

## Data Layer (`app/journals/ap_journal_data.py`)

`build_columnar` gains a `voided_bills` parameter (list of `PurchaseBill`, default `[]`).

For each voided bill, one row is appended:

```python
{'bill': bill, 'cells': {}, 'is_voided': True}
```

- `cells` is empty — no amounts, no column contribution.
- `is_voided=True` distinguishes the row from posted (`is_draft=False`) and draft (`is_draft=True`) rows.
- The bill object carries all identity fields (bill_number, vendor_invoice_number, vendor_name, notes, bill_date).
- Sorting: voided rows join the chronological sort by `bill.bill_date` then `bill.bill_number`. Posted/draft rows sort by `entry.entry_date` + `entry.entry_number`. A unified sort key handles both.
- Voided rows do **not** contribute to `totals` or `grand_total`.

## View Layer (`app/journals/views.py`)

`_ap_journal_context` fetches voided bills within the period:

```python
voided_bills = PurchaseBill.query.filter(
    PurchaseBill.branch_id == branch_id,
    PurchaseBill.status == 'voided',
    PurchaseBill.bill_date >= period['date_from'],
    PurchaseBill.bill_date <= period['date_to'],
).all()
```

These are passed to `build_columnar(posted, drafts, ap_id, wt_id, vat_ids, voided_bills=voided_bills)`.

The existing `bill_map` (for resolving vendor info on posted/draft rows) is unchanged. Voided rows already carry the bill object directly, so they skip the map.

The Excel export (`build_ap_journal_xlsx`) is updated to handle `is_voided` rows the same way it handles `is_draft` rows — identity columns populated, amount columns blank.

## Template (`app/templates/journals/ap_journal.html`)

Voided rows:

| Element | Treatment |
|---|---|
| Row class | `table-danger` (red tint) |
| APV No. | Struck-through + red `VOIDED` badge |
| Vendor Invoice No. | Struck-through |
| Vendor | Struck-through |
| Particulars | Struck-through |
| Amount columns | Blank (no dashes) |
| Totals row | Unaffected |

## AP List (`app/templates/purchase_bills/list.html`)

Confirm that voided bills already display a `VOIDED` status badge. No query changes needed — the list already returns all statuses when `status=all`.

## Out of Scope

- Sales Invoice void display (separate module, different void semantics — creates a reversal JE).
- Receipt/JE cancel display in their respective journals.
- Changing the void handler (JE deletion on void remains correct).
