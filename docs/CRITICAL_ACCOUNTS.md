# Critical Chart of Accounts

This document describes the critical accounts that are automatically loaded when initializing the CAS database. These accounts are essential for the application to function properly and comply with Philippine BIR requirements.

## Overview

**Total Critical Accounts**: 43 accounts
- **Assets**: 11 accounts
- **Liabilities**: 11 accounts
- **Equity**: 4 accounts
- **Revenue**: 5 accounts
- **Expenses**: 12 accounts

## Account Categories

### ASSETS (11 accounts)

#### Current Assets

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 1000 | Cash on Hand | Debit | Cash physically held by the company |
| 1010 | Cash in Bank | Debit | Cash deposited in bank accounts |
| 1100 | Accounts Receivable | Debit | **CRITICAL** - Amounts owed by customers (AR/invoicing) |
| 1110 | Allowance for Doubtful Accounts | Credit | Contra-asset for uncollectible receivables |
| 1200 | Input Tax | Debit | **BIR CRITICAL** - VAT paid on purchases (monthly account) |
| 1210 | Creditable Withholding Tax | Debit | **BIR CRITICAL** - Withholding taxes that can be credited |
| 1220 | Excess Input Tax Carry Over | Debit | **BIR CRITICAL** - Excess input tax from previous months |
| 1300 | Inventory | Debit | Goods held for sale |
| 1400 | Prepaid Expenses | Debit | Expenses paid in advance |

#### Non-Current Assets

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 1500 | Property, Plant and Equipment | Debit | Fixed assets |
| 1510 | Accumulated Depreciation | Credit | Contra-asset for depreciation |

---

### LIABILITIES (11 accounts)

#### Current Liabilities

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 2000 | Accounts Payable | Credit | **CRITICAL** - Amounts owed to suppliers (AP/bills) |
| 2100 | Output Tax | Credit | **BIR CRITICAL** - VAT collected on sales (monthly account) |
| 2105 | VAT Payable | Credit | **BIR CRITICAL** - Net VAT payable to BIR (month-end closing account) |
| 2110 | Withholding Tax Payable - Expanded | Credit | **BIR CRITICAL** - Expanded withholding tax payable to BIR |
| 2120 | Withholding Tax Payable - Compensation | Credit | **BIR CRITICAL** - Compensation withholding tax from salaries |
| 2200 | SSS Payable | Credit | **PH STATUTORY** - Social Security System contributions |
| 2210 | PhilHealth Payable | Credit | **PH STATUTORY** - Philippine Health Insurance contributions |
| 2220 | Pag-IBIG Payable | Credit | **PH STATUTORY** - Home Development Mutual Fund contributions |
| 2300 | Salaries and Wages Payable | Credit | Unpaid employee compensation |
| 2400 | Accrued Expenses | Credit | Expenses incurred but not yet paid |

#### Non-Current Liabilities

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 2500 | Long-term Loans Payable | Credit | Loans payable beyond one year |

---

### EQUITY (4 accounts)

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 3000 | Capital Stock | Credit | **CRITICAL** - Ownership capital |
| 3100 | Retained Earnings | Credit | **CRITICAL** - Accumulated profits/losses |
| 3200 | Retained Earnings - Unappropriated | Credit | Unappropriated retained earnings |
| 3300 | Drawings/Dividends | Debit | Distributions to owners |

---

### REVENUE (5 accounts)

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 4000 | Sales Revenue | Credit | **CRITICAL** - Revenue from goods sold |
| 4100 | Service Revenue | Credit | **CRITICAL** - Revenue from services |
| 4200 | Sales Returns and Allowances | Debit | Contra-revenue for returns |
| 4300 | Sales Discounts | Debit | Contra-revenue for discounts given |
| 4400 | Other Income | Credit | Non-operating income |

---

### EXPENSES (12 accounts)

#### Cost of Sales

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 5000 | Cost of Goods Sold | Debit | **CRITICAL** - Direct costs of goods sold |
| 5100 | Cost of Services | Debit | Direct costs of services provided |

#### Operating Expenses

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 5200 | Salaries and Wages Expense | Debit | **CRITICAL** - Employee compensation |
| 5300 | Rent Expense | Debit | Rental payments |
| 5400 | Utilities Expense | Debit | Electricity, water, internet, etc. |
| 5500 | Depreciation Expense | Debit | Depreciation of fixed assets |
| 5600 | Professional Fees | Debit | Legal, accounting, consulting fees |
| 5700 | Taxes and Licenses | Debit | Business taxes and permits |
| 5800 | Office Supplies Expense | Debit | Office supplies consumed |
| 5900 | Miscellaneous Expense | Debit | Other miscellaneous expenses |

#### Other Expenses

| Code | Account Name | Normal Balance | Purpose |
|------|-------------|----------------|---------|
| 6000 | Interest Expense | Debit | Interest on loans |
| 6100 | Bank Charges | Debit | Bank service fees |

---

## BIR Compliance Accounts (Critical)

These accounts are **essential** for Philippine BIR compliance and must be present for the application to handle VAT and withholding tax correctly:

### VAT Accounts

**Input Side (Assets)**
- **1200 - Input Tax**: VAT paid on purchases during the month (12% of purchase amount)
- **1210 - Creditable Withholding Tax**: Withholding taxes withheld by customers that can be credited against tax liabilities
- **1220 - Excess Input Tax Carry Over**: Excess input tax from previous months carried forward

**Output Side (Liabilities)**
- **2100 - Output Tax**: VAT collected on sales during the month (12% of sales amount via company invoices)
- **2105 - VAT Payable**: Net VAT liability payable to BIR after month-end closing (Output Tax - Input Tax)

**Month-End Process:**
Every month, Input Tax (1200) and Output Tax (2100) are closed to either:
- VAT Payable (2105) if Output Tax > Input Tax, or
- Excess Input Tax Carry Over (1220) if Input Tax > Output Tax

See [VAT_ACCOUNTS_EXPLANATION.md](VAT_ACCOUNTS_EXPLANATION.md) for detailed explanation.

### Withholding Tax Accounts (Liabilities)
- **2110 - Withholding Tax Payable - Expanded**: Withholding taxes withheld from suppliers (various ATC codes)
- **2120 - Withholding Tax Payable - Compensation**: Withholding taxes withheld from employee salaries

### Philippine Statutory Deductions (Liabilities)
- **2200 - SSS Payable**: Social Security System contributions
- **2210 - PhilHealth Payable**: Philippine Health Insurance contributions
- **2220 - Pag-IBIG Payable**: Home Development Mutual Fund contributions

---

## Application Functionality Requirements

### For Accounts Receivable (AR) / Invoicing
**Required Accounts:**
- 1100 - Accounts Receivable
- 4000 - Sales Revenue
- 4100 - Service Revenue
- 1210 - Creditable Withholding Tax (for withholding)
- 2100 - Output Tax (for daily VAT on invoices)
- 2105 - VAT Payable (for month-end VAT closing)

### For Accounts Payable (AP) / Bills
**Required Accounts:**
- 2000 - Accounts Payable
- 1200 - Input Tax (for VAT)
- 2110 - Withholding Tax Payable - Expanded (for withholding)

### For Financial Statements
**Required Accounts:**
- All Asset accounts (for Balance Sheet)
- All Liability accounts (for Balance Sheet)
- All Equity accounts (for Balance Sheet)
- All Revenue accounts (for Income Statement)
- All Expense accounts (for Income Statement)

### For Payroll Processing
**Required Accounts:**
- 5200 - Salaries and Wages Expense
- 2300 - Salaries and Wages Payable
- 2120 - Withholding Tax Payable - Compensation
- 2200 - SSS Payable
- 2210 - PhilHealth Payable
- 2220 - Pag-IBIG Payable

---

## Customization

While these accounts are critical for basic functionality, organizations can:

1. **Add more accounts** as needed for their specific operations
2. **Create sub-accounts** using the parent_id relationship (e.g., multiple bank accounts under Cash in Bank)
3. **Customize account names** while preserving the account codes and types

### Example: Adding Sub-accounts

```python
# Create a sub-account under Cash in Bank (1010)
Account(
    code='1011',
    name='BDO Checking Account',
    account_type='Asset',
    classification='Current',
    normal_balance='Debit',
    parent_id=<id_of_account_1010>
)
```

---

## Maintenance

These critical accounts are loaded automatically when initializing a fresh database via:

1. **load_fixtures.py** script
2. **init_db.py** script
3. **recreate_db_with_migrations.py** script

The accounts are defined in [app/fixtures.py](app/fixtures.py) in the `load_sample_chart_of_accounts()` function.

---

## Important Notes

⚠️ **DO NOT DELETE** critical accounts marked as **CRITICAL** or **BIR CRITICAL** as this will break application functionality.

⚠️ **BIR Compliance**: The VAT and withholding tax accounts must match the account codes used in [app/static/js/app.js](app/static/js/app.js):
- Input Tax account code: `1200` (referenced as `inputTaxAccount`)
- Output Tax code: `2100` (referenced as `OUTPUT_VAT_ACCOUNT`) - **Note:** This is for daily transactions; month-end closing uses VAT Payable (2105)
- Creditable Withholding Tax code: `1210` (referenced as `CWT_RECEIVABLE_ACCOUNT`)

⚠️ **Monthly VAT Closing**: Accounts 1200 (Input Tax) and 2100 (Output Tax) must be closed to zero every month. The net difference goes to either 2105 (VAT Payable) or 1220 (Excess Input Tax Carry Over). See [VAT_ACCOUNTS_EXPLANATION.md](VAT_ACCOUNTS_EXPLANATION.md) for the complete process.

⚠️ **Account Numbering**: The account code structure follows the standard chart of accounts numbering:
- 1000-1999: Assets
- 2000-2999: Liabilities
- 3000-3999: Equity
- 4000-4999: Revenue
- 5000-6999: Expenses

---

## Related Documentation

- [VAT_ACCOUNTS_EXPLANATION.md](VAT_ACCOUNTS_EXPLANATION.md) - **Detailed VAT accounting process and month-end closing**
- [CLAUDE.md](CLAUDE.md) - Development guidelines
- [DATABASE_INITIALIZATION.md](DATABASE_INITIALIZATION.md) - Database initialization guide
- [app/fixtures.py](app/fixtures.py) - Source code for default fixtures
- [app/static/js/app.js](app/static/js/app.js) - Frontend VAT/withholding tax logic

---

## Version History

- **v1.0** - Initial critical accounts (41 accounts)
  - Includes BIR compliance accounts
  - Philippine statutory deduction accounts
  - Core accounting functionality accounts
