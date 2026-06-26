# Legacy → CAS transaction mapping

Working record of how each legacy `data.db` document type enters CAS. Built one type at
a time. Source profiling + the account crosswalk (`instance/uploads/legacy_coa_map.json`,
legacy `account_id` → CAS account id, 340/340) are prerequisites for all of these.

Branch split: legacy main tables → **Corp** (branch_id 1); `_x` tables → **Extra** (branch_id 2).
Doing **Corp first**.

---

## 1. SALES → CAS Sales Invoice  *(mapping recorded; import blocked on customers)*

**Legacy:** `sales` (5,193 Corp / 2,498 `sales_x`) + `sales_entry`. Header: `record_date`,
`sales_number`, `invoice_number` (mostly blank), `notes` (mostly blank), `customer_id`,
`date_posted`. Lines: `account_id, debit, credit`.

**Finding — every legacy sale is a regular 12% VATable sale with 1% creditable WHT.**
Only 5 accounts ever appear. Canonical shape (verified on real docs):

```
Dr  ACCOUNTS RECEIVABLE-TRADE   (11201)   = revenue + VAT − CWT
Dr  CREDITABLE WITHHOLDING TAX  (12501)   = 1% × revenue
Cr  SALES - Tincan / Plastic    (41101/41201) = revenue
Cr  OUTPUT TAX                  (22103-1) = 12% × revenue
```
Example #0029235: revenue 324,993.50 → VAT 38,999.22 (12% ✓), CWT 3,249.94 (1% ✓),
AR 360,742.78 (= rev+VAT−CWT ✓).

**→ Enters CAS as a Sales Invoice** (SI module), which *regenerates* this GL. Proposed field map:

| CAS Sales Invoice | From legacy |
|---|---|
| invoice_date | `record_date` |
| customer | `customer_id` → CAS customer (via customer map — TBD) |
| invoice_number / doc no | `sales_number` (and/or `invoice_number`) |
| notes | `notes` |
| status | posted (legacy sales all have `date_posted`) |
| branch | Corp (sales) / Extra (sales_x) |
| line.amount (VAT-INCLUSIVE) | revenue × 1.12 (CAS extracts the 12% VAT) |
| line.account | product revenue acct (41101 Tincan / 41201 Plastic) — **verify SI line takes an account** |
| line.vat_category | **V12** (12%); VEX/V0 for the ~521 sales with no Output Tax |
| line.wht | **WC158** (1% goods) — present on nearly all |

**Variations to handle:** ~521 sales have no Output Tax → VAT-exempt/zero-rated (VEX/V0);
some docs credit BOTH Tincan + Plastic → two line items; a few may lack CWT.

**Prerequisites:** customers imported (the `customer_id` map); revenue accounts 41101/41201
(done, in COA); sales VAT category V12 (exists); WHT WC158=1% (exists).

**Open / to verify before importing:**
- Does the CAS `SalesInvoice` line let you choose the revenue account (41101 vs 41201)?
- Confirm WC158 is the right 1% creditable-WHT code for a sale (seller POV).
- Confirm CAS's VAT extraction on a VAT-inclusive line reproduces the legacy VAT to the centavo.
- ~521 non-VAT sales: VEX vs V0?
- Method (per-type, still open): scripted SI create endpoint vs direct DB (SI + lines + JournalEntry).

---

## 2. RECEIPTS → (CRV)  — *not yet mapped*
## 3. DISBURSEMENTS → (CDV)  — *not yet mapped*
## 4. ACCOUNTS_PAYABLE → (APV)  — *not yet mapped*
## 5. GENERAL → (Journal Voucher)  — *not yet mapped*
## 6. PETTY_CASH → (?)  — *not yet mapped (no CAS petty-cash module)*
