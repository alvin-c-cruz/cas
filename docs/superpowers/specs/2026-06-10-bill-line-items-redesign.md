# Purchase Bill Line Items Redesign

## Goal

Simplify the line items table to 5 columns, replace qty × unit_cost with a single VAT-inclusive Amount, add editable override fields for Input VAT and WHT in the totals panel, add a live journal entry preview, and post a balanced JE to the general ledger when a bill is saved.

---

## Line Items Table

### Columns (in order)

| # | Header | Type | Notes |
|---|--------|------|-------|
| 1 | Description | text input | unchanged |
| 2 | Amount | number input | VAT-inclusive; right-aligned monospace |
| 3 | VT | select | VAT category (code + rate%) |
| 4 | WT | select | WHT code (code + rate%); vendor defaults pre-selected |
| 5 | Account Title | select | Expense account from COA |
| — | *(delete)* | button | 🗑️ icon; unchanged |

Qty and Unit Cost columns are removed entirely.

---

## Calculations

All computed per line:

```
net_base    = amount / (1 + vat_rate / 100)   # ex-VAT base; if vat_rate = 0, net_base = amount
vat_amount  = amount - net_base               # extracted input VAT
wht_amount  = net_base × wht_rate / 100       # WHT on net base (BIR EWT standard)
line_total  = amount                          # VAT-inclusive; used for subtotal
```

Bill-level totals:

```
subtotal    = sum(line_total)                 # VAT-inclusive gross
input_vat   = sum(vat_amount)                 # or overridden value
wht_total   = sum(wht_amount)                 # or overridden value
net_payable = subtotal - wht_total
```

---

## Totals Panel

```
Subtotal          ₱13,440.00
Input VAT   ✏️    ₱1,440.00
─────────────────────────────
Withholding Tax ✏️  −₱200.00
─────────────────────────────
Net Payable       ₱13,240.00

[ Enter Bill ]
```

### Override UX — pencil pattern (Option B)

- Each amount (Input VAT, WHT) renders as plain text with a faint pencil icon (✏️) on hover.
- Clicking the pencil replaces the text with a number `<input>` focused and ready to type.
- A ↺ reset icon appears alongside the input; clicking it reverts to the auto-computed value and exits edit mode.
- While in edit mode, the original auto value is shown below the input as a small grey hint: `auto: ₱1,440.00`.
- Net Payable and the JE preview update live as the user types.
- Changing Amount or VT on a line resets any Input VAT override (recalculates). Changing WT resets any WHT override.

---

## Journal Entry Preview

Displayed below the line items, to the left of the totals panel. Updates live.

| Code | Account Title | Debit | Credit |
|------|--------------|-------|--------|
| 6100 | Rent Expense | 10,000.00 | — |
| 6200 | Office Supplies | 2,000.00 | — |
| 10501 | Input VAT - Current | 1,440.00 | — |
| 20301 | WHT Payable - Expanded | — | 200.00 |
| 20101 | Accounts Payable - Trade | — | 13,240.00 |
| | **Total** | **13,440.00** | **13,440.00** |

**Account sources (hardcoded, matching existing reversal pattern):**
- Expense lines: `account_id` from each line item
- Input VAT: account code `10501` (Input VAT - Current)
- WHT Payable: account code `20301` (WHT Payable - Expanded); omitted if wht_total = 0
- Accounts Payable: account code `20101` (Accounts Payable - Trade)
- Expense debit amount = `net_base` per line (ex-VAT)

**JE balance with overrides:**

The JE must always balance. The authoritative amounts are:
- `input_vat_used` = override value if `vat_override`, else `sum(line.vat_amount)`
- `wht_used` = override value if `wt_override`, else `sum(line.wt_amount)`
- AP credit = `subtotal − wht_used` (AP reflects actual amount owed to vendor)
- Expense debit per line = `line.net_base` as computed from the line's own rate
- Input VAT debit = `input_vat_used`

If `input_vat_used ≠ sum(line.vat_amount)`, total debits ≠ total credits by the difference. To absorb it: the first expense line's debit is adjusted by `(sum(net_base) + input_vat_used) − subtotal`. In practice this is a rounding difference of ₱0.01–₱0.05.

---

## Journal Entry Posting

When the bill is saved (Enter Bill / Update Bill), a balanced `JournalEntry` is created and immediately posted (`status = 'posted'`).

- `entry_type = 'purchase'` — new value added to the choices list
- `reference = bill.bill_number`
- `description = f"Purchase Bill {bill.bill_number} — {bill.vendor_name}"`
- `entry_date = bill.bill_date`
- `branch_id = bill.branch_id`
- The bill stores a FK `journal_entry_id` pointing to this JE.

On **edit**, the old JE is deleted and a new one is created to reflect current amounts.

On **void/cancel**, the existing reversal JE logic (`_create_reversal_je()`) remains unchanged.

---

## Model Changes

### `PurchaseBillItem`

| Change | Field | Detail |
|--------|-------|--------|
| Rename | `unit_cost` → `amount` | Numeric(15,2); VAT-inclusive |
| Drop | `quantity` | No longer used |
| Unchanged | `line_total` | Now equals `amount` (set in `calculate_amounts()`) |
| Unchanged | `vat_amount` | Now = `amount - net_base` |
| Unchanged | `wt_amount` | Now = `net_base × wt_rate / 100` |

`calculate_amounts()` rewrite:
```python
net_base = self.amount / (1 + self.vat_rate / 100) if self.vat_rate else self.amount
self.line_total = self.amount
self.vat_amount = round(self.amount - net_base, 2)
self.wt_amount = round(net_base * (self.wt_rate / 100), 2) if self.wt_rate else Decimal('0')
```

### `PurchaseBill`

| Change | Field | Type | Default |
|--------|-------|------|---------|
| Add | `vat_override` | Boolean | False |
| Add | `wt_override` | Boolean | False |
| Add | `journal_entry_id` | FK → JournalEntry, nullable | None |

`calculate_totals()` update: if `vat_override=True`, preserve `self.vat_amount` (the submitted value); otherwise recompute from lines. Same for `wt_override` / `self.withholding_tax_amount`.

### `JournalEntry`

| Change | Field | Detail |
|--------|-------|--------|
| Add choice | `entry_type` | Add `'purchase'` to the existing choices list |

---

## Data Migration

- All bills were cleared before this change (clean slate) — no data backfill needed.
- Migration: rename column `unit_cost` → `amount`, drop column `quantity`, add `vat_override`, `wt_override`, `journal_entry_id` to `purchase_bills`, add `'purchase'` to journal_entries entry_type check constraint (if any).

---

## Files Changed

| File | Change |
|------|--------|
| `app/purchase_bills/models.py` | Rename field, drop field, add 3 fields, rewrite `calculate_amounts()` |
| `app/purchase_bills/views.py` | Update line item JSON parsing; handle `vat_override`/`wt_override`; add JE posting logic; delete+recreate JE on edit |
| `app/purchase_bills/templates/purchase_bills/form.html` | New 5-col table; override UX in totals panel; JE preview section |
| `app/purchase_bills/templates/purchase_bills/detail.html` | Remove Qty/Unit Cost columns; show Amount column |
| `app/journal_entries/models.py` | Add `'purchase'` to `entry_type` choices |
| `migrations/` | One Alembic migration covering all model changes above |
| `tests/integration/test_purchase_bill_views.py` | Update existing tests; add JE posting assertion |

---

## What Does NOT Change

- Vendor defaults loading (WHT, VAT pre-selection, payment terms)
- Header fields layout (AP Number, Voucher Date, Due Date, etc.)
- `generate_bill_number()`, bill status workflow, approval flow
- Void/cancel reversal JE logic (`_create_reversal_je()`)
- AP Aging report
