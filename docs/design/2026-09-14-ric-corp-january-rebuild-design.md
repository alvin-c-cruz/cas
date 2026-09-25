# RIC CORP January 2026 rebuild: sales invoices only, through the app's own screens

**Date:** 2026-09-14 · **Status:** spec, awaiting owner approval · **Client:** RIC (Rowell Industrial Corporation), branch CORP (id 1)

## Goal

Re-create RIC's January 2026 CORP sales in CAS from scratch as posted Sales Invoices, each one
created and posted through the same HTTP handlers the screen uses, so the result is exactly what
hand entry would produce: numbering checks, line parsing, totals, journal entry, audit rows.
No sales orders, no delivery receipts, no raw SQL.

## What exists today

- `cas/instance/ric.db` was cleared of all documents on 2026-09-13. January 2026 EXTRA (79
  invoices, `0013935`–`0014013`) is re-imported and posted. CORP has nothing.
- The legacy accounting app (`alvinltv.pythonanywhere.com`) had **no CORP sales after
  2025-12-24** in the July 30 backup. The owner states it has since been updated. It carries
  amounts and tax legs only, no products or prices.
- The legacy invoice-printing app (`michellecaliwag.pythonanywhere.com`; local backup
  `C:\envs\erp-workspace\clients\ric\legacy-apps\sales_invoice\instance\data.db`) holds
  **129 January 2026 CORP invoices** (`34027`–`34156`): number, date, customer, customer PO
  (`so_number`), DR number, salesman, and lines with product, quantity, unit price.
  Five of them (`34032`, `34066`, `34067`, `34068`, `34087`) are CANCELLED placeholders with no
  lines. Number `34029` exists nowhere.
- The pre-clean CAS backup exists but is **out of bounds for this rebuild** by owner decision.
- The operations app backup (`…\rowell_indutrial_flask\instance\ric_data.db`) has 126 January
  delivery receipts, 2 cancelled. The 124 live ones map one-to-one onto the 124 real invoices by
  DR number, none used twice, none missing either way. (`34156` is DR `25146`; the pre-clean CAS
  had linked it to `25168`, which was RIC's keying error, not a missing delivery.)

## Decision log

| # | Decision | Ruling (owner, 2026-09-14) |
|---|---|---|
| 1 | Source of truth | **Invoice-printing app (michellecaliwag) for the document: number, date, customer, PO, DR, salesman, products, quantities, prices. Accounting app (alvinltv, updated) for the entry: sales, output VAT and withholding legs per invoice, used as the per-invoice cross-check.** The pre-clean CAS backup is **not consulted at all** (owner, 2026-09-14). Both sources are re-downloaded from PythonAnywhere before the run, since the local July 30 copies predate the accounting update. |
| 2 | Cancelled numbers | **Record the five CANCELLED numbers as voided CAS invoices** so the printed series shows them. **`34029` stays a gap**, flagged for RIC to explain. |
| 3 | Line detail | **Product, quantity (PCS), unit price**, description blank. **Products are matched by exact legacy name; a legacy name with no exact CAS match is created as a new CAS product under that exact name** (owner, 2026-09-14: "use the legacy name"). 41 of the 60 January names exist exactly; 19 will be created. No name-similarity mapping, no backup lookup. |
| 4 | Pre-posting gate | **Post the clean ones, list the exceptions.** Every invoice must pass its own checks to post; failures are held back and reported for ruling. |
| 5 | Salesperson | **Create Jing Hipolito as an employee first**, then map Embalsado, Go, Hipolito; "OFFICE ACCOUNT" and blanks post under the Company Account. The legacy salesman name is always kept in the particulars. |
| 6 | Payment terms | **Net 60** for every RIC customer (already set on all 21 customer records); due date = invoice date + 60. |
| 7 | Invoice number | **RIC's own number** from the invoice app (`34027` onward). No reference value. |
| 8 | Tax | Every CORP line is **VAT-inclusive 12% (`V12`) with 1% creditable WHT (`WC158`)**, the shape of every legacy CORP sale (Dr AR, Dr CWT 1%, Cr Sales, Cr Output Tax 12%). CAS derives output VAT and WHT; nothing is keyed by hand; the accounting app's legs are the per-invoice proof (check 3). |
| 9 | Scope kept | The 79 January EXTRA invoices stay as they are. Out of scope: opening balances, cash receipts, February onward, sales orders, delivery receipts, stock, the live PythonAnywhere copy. |

## Field mapping (invoice app → CAS Sales Invoice)

| CAS field | From |
|---|---|
| `branch` | CORP (session `selected_branch_id` = 1) |
| `invoice_number` | `invoice.invoice_number` |
| `invoice_date` | `invoice.record_date` |
| `due_date` | `record_date + 60 days`; `payment_terms` = `Net 60` |
| `customer_id` | `customer.name`, trimmed, via the name map below |
| `customer_po_number` | `invoice.so_number` as printed (it is the customer's PO; a few carry a DR-style number, copied as is) |
| `salesperson_id` | `invoice.sales_man` via the salesperson map; else 0 (Company Account) |
| `reference` | blank |
| `notes` (particulars) | `Copied from legacy invoice <no> (michellecaliwag.pythonanywhere.com), <MM/DD/YYYY>, <customer>, DR <dr_number>, salesman <name>` |
| line `product_id`, `quantity`, `unit_price` | `invoice_entry`, product by exact legacy name (created if absent); `uom_text` = `PCS`; `description` blank; `vat_category` = `V12`; `wt_id` = WC158's id; `account_id` = `411001` Sales - Tincan when the accounting app's entry credits 41101, `411005` Sales - Plastic when it credits 41201 (check 3 fails if the entry has neither) |

Name maps:

- Customers: `DAVIES PAINTS PHILIPPINES` → `DAVIES PAINTS PHILIPPINES INC.`; `CONSTRUCTION CHEMICAL TECHNOLOGIES INC. ` (trailing space) → `CONSTRUCTION CHEMICAL TECHNOLOGIES INC.`; the other four are exact.
- Salespersons: `CORAZON EMBALSADO` → EMP-001; `EUGENE GO` → EMP-0002; `JING HIPOLITO` → the new employee (EMP-0003, salesperson, branch CORP); `OFFICE ACCOUNT` and blank → 0.
- Products: exact-name match on `products.name`. The 19 January names with no exact match are created through the product create route before invoicing, with `track_inventory` off, the legacy name as the product name, no code, and the category set from the accounting app's sales leg for the invoice that first uses it (41101 → TINCAN, 41201 → PLASTIC). Nine of the 19 are punctuation variants of existing CAS names (e.g. `CAN-PROTECTO AP 4L (BLUE)` vs `CAN PROTECTO AP 4L (BLUE)`); the run report lists them so RIC can merge later if it wants. The created products are listed in the run report.

## Cancelled numbers

For each of `34032`, `34066`, `34067`, `34068`, `34087`: create a draft on the `CANCELLED` customer,
dated as in the invoice app, one amount-only line of `0.00` to `411001` (if CAS refuses a zero
line, `0.01` reversed by the void), particulars `Cancelled in legacy invoice series`, then call
the void route with reason `Cancelled in legacy invoice series (invoice app)`. Result: status
`voided`, no journal entry, number preserved. `34029` is not created; it is listed in the run
report as `gap: not in invoice app, not in accounting app, not in CAS backup`.

## Pre-posting checks (per invoice, and for the run)

Per invoice, all must hold or the invoice is held back:

1. **DR match.** Its DR number exists in the operations app's January list and is not cancelled
   there, and no other invoice uses the same DR.
2. **Lines complete.** Every line's product maps; qty and unit price present; gross =
   Σ qty × unit price to the centavo.
3. **Accounting-app agreement.** The accounting app's January CORP entry with the same invoice number exists and its legs match what CAS will compute: Cr Sales = gross ÷ 1.12, Cr Output Tax = 12% of that, Dr CWT = 1% of that, Dr AR = the remainder, each to the centavo.
4. **Post-check.** After posting, the JE has exactly Dr AR, Dr CWT, Cr Output Tax, Cr Sales legs,
   balanced, with CWT = 1% and VAT = 12% of the net, and the invoice's total equals the gross.

For the run:

5. **Series.** Posted + voided numbers form `34027`–`34156` with `34029` the only gap.
6. **Accounting-journal tie-out.** The run's totals (net sales by account, output VAT, CWT, AR)
   equal the sum of the accounting app's January CORP entries.

The run report lists posted, voided, held-back (with the failing check), and the gap.

## Implementation order

0. Owner refreshes the two sources from PythonAnywhere (Files page of each account): `alvinltv` → `accounting/instance/data.db`, `michellecaliwag` → `sales_invoice/instance/data.db`, saved as dated copies under `C:\envs\erp-workspace\clients
ic\legacy-apps\...`; and confirms the 10 product mappings.
1. Create employee Jing Hipolito (Employees screen or script through the same route).
2. `tools/ric_import_legacy_sales_corp.py`, modelled on `ric_import_legacy_sales_x.py`: read the
   invoice app DB and the accounting app DB, resolve products by exact name (listing the ones to create), run checks 1–3, dry-run report.
2b. Real run first creates the missing products through the product route, then proceeds.
3. Real run: create + post each clean invoice through `/sales-invoices/create` and
   `/sales-invoices/<id>/post` with an admin session; void the five cancelled numbers; run
   checks 4–6; write the report.
4. Owner reviews the report and the held-back list; rules on `34029`.
5. Re-run for any held-back invoices once ruled (the script skips numbers already in CAS).

## Out of scope

Opening balances; cash receipts; February onward; sales orders and delivery receipts; stock;
the live PythonAnywhere copy; EXTRA (already done).
