# VAT Accounts Explanation

This document explains the VAT (Value Added Tax) accounting structure in the CAS system, specifically designed for Philippine BIR compliance.

## Overview

The CAS system uses a **separate account structure** for tracking VAT throughout the month and then closing to final accounts at month-end. This provides better tracking and reporting for BIR compliance.

## VAT Account Structure

### Asset Accounts (Input Side)

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| **1200** | Input Tax | Debit | Daily VAT paid on purchases (12% on goods/services purchased) |
| **1210** | Creditable Withholding Tax | Debit | Withholding taxes withheld by customers (creditable against tax liabilities) |
| **1220** | Excess Input Tax Carry Over | Debit | Excess input tax from previous months carried forward |

### Liability Accounts (Output Side)

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| **2100** | Output Tax | Credit | Daily VAT collected on sales (12% on goods/services sold via company invoices) |
| **2105** | VAT Payable | Credit | Monthly closing account for net VAT liability payable to BIR |

---

## How VAT Accounts Work

### During the Month (Daily Transactions)

#### When Making Sales (AR/Invoicing):
```
Example: Issue invoice for ₱11,200 (₱10,000 + ₱1,200 VAT)

DR  Accounts Receivable (1100)          11,200
    CR  Sales Revenue (4000)                     10,000
    CR  Output Tax (2100)                         1,200
```

#### When Making Purchases (AP/Bills):
```
Example: Receive bill for ₱11,200 (₱10,000 + ₱1,200 VAT)

DR  Expense/Inventory Account           10,000
DR  Input Tax (1200)                     1,200
    CR  Accounts Payable (2000)                  11,200
```

### Month-End Closing (VAT Closing Entries)

At the end of each month, **all Input Tax and Output Tax balances are closed** to determine the net VAT position:

#### Scenario 1: Output Tax > Input Tax (Company Owes VAT to BIR)
```
Example:
- Output Tax (2100) balance: ₱120,000 CR
- Input Tax (1200) balance: ₱80,000 DR
- Net VAT Payable: ₱40,000

Closing Entry:
DR  Output Tax (2100)                    120,000
    CR  Input Tax (1200)                          80,000
    CR  VAT Payable (2105)                        40,000

Result: Company must pay ₱40,000 to BIR
```

#### Scenario 2: Input Tax > Output Tax (Excess Input Tax)
```
Example:
- Output Tax (2100) balance: ₱80,000 CR
- Input Tax (1200) balance: ₱120,000 DR
- Excess Input Tax: ₱40,000

Closing Entry:
DR  Output Tax (2100)                     80,000
DR  Excess Input Tax Carry Over (1220)   40,000
    CR  Input Tax (1200)                         120,000

Result: ₱40,000 excess input tax carried forward to next month
```

#### Scenario 3: Input Tax = Output Tax (Zero VAT Position)
```
Example:
- Output Tax (2100) balance: ₱100,000 CR
- Input Tax (1200) balance: ₱100,000 DR
- Net VAT: ₱0

Closing Entry:
DR  Output Tax (2100)                    100,000
    CR  Input Tax (1200)                         100,000

Result: No VAT payable, no excess to carry over
```

---

## Month-End VAT Closing Process

### Step 1: Calculate Net VAT Position
```
Net VAT = Output Tax Balance - Input Tax Balance - Excess Input Tax Carry Over (from previous month)
```

### Step 2: Determine the Closing Entry

**If Net VAT is Positive (Company owes BIR):**
```
DR  Output Tax (2100)                    [Output Tax Balance]
DR  Excess Input Tax Carry Over (1220)  [Previous month's excess, if any]
    CR  Input Tax (1200)                 [Input Tax Balance]
    CR  VAT Payable (2105)               [Net VAT to pay BIR]
```

**If Net VAT is Negative (Excess Input Tax):**
```
DR  Output Tax (2100)                    [Output Tax Balance]
DR  Excess Input Tax Carry Over (1220)  [New excess to carry forward]
    CR  Input Tax (1200)                 [Input Tax Balance]
    CR  Excess Input Tax Carry Over (1220) [Previous month's excess, if any]
```

### Step 3: File BIR Returns
- File BIR Form 2550M (Monthly VAT Declaration)
- Pay the VAT Payable (2105) balance to BIR by the 20th of the following month
- Record payment:
  ```
  DR  VAT Payable (2105)                [Amount paid]
      CR  Cash in Bank (1010)            [Amount paid]
  ```

---

## Example: Complete Monthly Cycle

### Month: January 2026

**Daily Transactions:**
- Total Sales: ₱1,000,000 + ₱120,000 Output Tax = ₱1,120,000
- Total Purchases: ₱800,000 + ₱96,000 Input Tax = ₱896,000

**Account Balances at Month-End (Jan 31):**
- Output Tax (2100): ₱120,000 CR
- Input Tax (1200): ₱96,000 DR
- Net VAT to pay: ₱24,000

**Month-End Closing Entry (Jan 31):**
```
DR  Output Tax (2100)                    120,000
    CR  Input Tax (1200)                          96,000
    CR  VAT Payable (2105)                        24,000

Narration: To close Input Tax and Output Tax to VAT Payable for January 2026
```

**After Closing:**
- Output Tax (2100): ₱0 (closed)
- Input Tax (1200): ₱0 (closed)
- VAT Payable (2105): ₱24,000 CR (owed to BIR)

**File BIR Return (by Feb 20):**
- File Form 2550M showing ₱24,000 VAT payable
- Pay ₱24,000 to BIR

**Payment Entry (Feb 20):**
```
DR  VAT Payable (2105)                   24,000
    CR  Cash in Bank (1010)                       24,000

Narration: Payment of VAT for January 2026 per BIR Form 2550M
```

**After Payment:**
- VAT Payable (2105): ₱0 (paid)

---

## Benefits of This Structure

### 1. **Clear Monthly Tracking**
- Input Tax (1200) and Output Tax (2100) accumulate daily transactions
- Easy to see monthly VAT activity

### 2. **Proper Month-End Closing**
- Formal closing entries create audit trail
- VAT Payable (2105) shows exact amount owed to BIR

### 3. **BIR Compliance**
- Matches BIR Form 2550M reporting requirements
- Clear separation between daily operations and monthly obligations

### 4. **Excess Input Tax Management**
- Excess Input Tax Carry Over (1220) properly tracks unused input tax
- Can be applied against future output tax or claimed from BIR

### 5. **Audit Trail**
- Every month's VAT position is clearly documented
- Easy to reconcile with BIR returns

---

## Common Scenarios

### Scenario A: Start of New Month with Excess Input Tax Carry Over

**Beginning of February (continuing from previous example):**
Assume January had excess input tax instead:

**Jan 31 Balances:**
- Output Tax (2100): ₱80,000 CR
- Input Tax (1200): ₱120,000 DR
- Excess: ₱40,000

**Closing Entry (Jan 31):**
```
DR  Output Tax (2100)                     80,000
DR  Excess Input Tax Carry Over (1220)   40,000
    CR  Input Tax (1200)                         120,000
```

**February transactions:**
- New Sales: ₱1,200,000 + ₱144,000 Output Tax
- New Purchases: ₱600,000 + ₱72,000 Input Tax

**Feb 28 Balances (before closing):**
- Output Tax (2100): ₱144,000 CR
- Input Tax (1200): ₱72,000 DR
- Excess Input Tax Carry Over (1220): ₱40,000 DR (from January)

**Calculate Net VAT:**
```
Net VAT = ₱144,000 - ₱72,000 - ₱40,000 = ₱32,000 (to pay BIR)
```

**Closing Entry (Feb 28):**
```
DR  Output Tax (2100)                    144,000
DR  Excess Input Tax Carry Over (1220)   40,000
    CR  Input Tax (1200)                          72,000
    CR  VAT Payable (2105)                        32,000
    CR  Excess Input Tax Carry Over (1220)       40,000

OR simplified:

DR  Output Tax (2100)                    144,000
    CR  Input Tax (1200)                          72,000
    CR  Excess Input Tax Carry Over (1220)       40,000
    CR  VAT Payable (2105)                        32,000
```

---

## Important Notes

⚠️ **Monthly Closing is Mandatory**
- Input Tax (1200) and Output Tax (2100) must be closed to ₱0 every month
- This ensures clean monthly VAT reporting

⚠️ **Timing**
- Month-end closing: Last day of the month
- BIR filing deadline: 20th of the following month
- Payment deadline: Same as filing (20th of following month)

⚠️ **Account Code References in Code**
The following account codes are hardcoded in [app/static/js/app.js](app/static/js/app.js):
- Input Tax: **1200** (`inputTaxAccount`)
- Output Tax: **2100** (`OUTPUT_VAT_ACCOUNT`)
- Creditable Withholding Tax: **1210** (`CWT_RECEIVABLE_ACCOUNT`)

**Do not change these account codes** without updating the JavaScript code!

⚠️ **Excess Input Tax Options**
When there is excess input tax, the company can either:
1. Carry it forward to offset future output tax (use account 1220)
2. Apply for refund from BIR (complex process, usually not preferred)
3. Most companies choose to carry forward

---

## Related BIR Forms

- **BIR Form 2550M** - Monthly Value-Added Tax Declaration
- **BIR Form 2550Q** - Quarterly Value-Added Tax Return (for quarters with no transactions)
- **BIR Form 1601-EQ** - Quarterly Remittance Return (for withholding taxes)

---

## Related Documentation

- [CRITICAL_ACCOUNTS.md](CRITICAL_ACCOUNTS.md) - Complete chart of accounts documentation
- [app/fixtures.py](app/fixtures.py) - Source code for default fixtures
- [app/static/js/app.js](app/static/js/app.js) - Frontend VAT calculation logic

---

## Version History

- **v1.1** (Current)
  - Changed "Output VAT Payable" to "Output Tax" (2100)
  - Added "VAT Payable" account for month-end closing (2105)
  - Added "Excess Input Tax Carry Over" account (1220)

- **v1.0**
  - Initial VAT account structure
  - Basic Input Tax and Output VAT Payable accounts
