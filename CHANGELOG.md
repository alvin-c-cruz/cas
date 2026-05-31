# CAS Changelog

## 2026-06-01: Philippine Standard Time & Critical Accounts Update

### Summary
Major update implementing Philippine Standard Time (UTC+8) throughout the application and establishing critical chart of accounts for BIR compliance and manufacturing operations.

---

### 1. Philippine Standard Time Implementation

**Files Modified:**
- `app/utils.py` - **NEW**: Philippine timezone utilities
- `app/__init__.py` - Updated template context processor
- `app/accounts/models.py` - Updated timestamps to use `ph_now()`
- `app/users/models.py` - Updated User and LoginHistory timestamps
- `app/users/views.py` - Updated login tracking to use `ph_now()`
- `app/branches/models.py` - Updated Branch timestamps
- `app/settings.py` - Updated AppSettings timestamps

**Implementation Details:**
```python
# Created PHT timezone constant and utility function
from datetime import datetime, timezone, timedelta

PHT = timezone(timedelta(hours=8))  # Philippine Standard Time (UTC+8)

def ph_now():
    """Get current datetime in Philippine Standard Time (UTC+8)."""
    return datetime.now(PHT)
```

**Changed all model defaults from:**
```python
created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

**To:**
```python
from app.utils import ph_now
created_at = db.Column(db.DateTime, default=ph_now)
```

**Impact:**
- All timestamps in database now use Philippine Standard Time
- Login history records accurate local time
- Audit trails show correct Philippine time
- Template context `now` variable uses Philippine time

**Verification:**
- Created `test_timezone.py` to verify 8-hour offset from UTC
- All tests pass - confirmed UTC+8 configuration

---

### 2. Critical Chart of Accounts

**Files Modified:**
- `app/fixtures.py` - Updated to include 35 critical accounts

**Account Structure:**

#### Assets (11 accounts)
- 1000: Cash on Hand
- 1010: Cash in Bank
- 1100: Accounts Receivable
- 1110: Allowance for Doubtful Accounts
- 1200: Input Tax (VAT paid on purchases)
- 1210: Creditable Withholding Tax
- 1220: Excess Input Tax Carry Over (for excess input VAT)
- 1300: Inventory
- 1400: Prepaid Expenses
- 1500: Property, Plant and Equipment
- 1510: Accumulated Depreciation

#### Liabilities (11 accounts)
- 2000: Accounts Payable
- 2100: Output Tax (VAT collected on sales)
- 2105: VAT Payable (month-end closing for net VAT to BIR)
- 2110: Withholding Tax Payable - Expanded
- 2120: Withholding Tax Payable - Compensation
- 2200: SSS Payable
- 2210: PhilHealth Payable
- 2220: Pag-IBIG Payable
- 2300: Salaries and Wages Payable
- 2400: Accrued Expenses
- 2500: Long-term Loans Payable

#### Equity (4 accounts)
- 3000: Capital Stock
- 3100: Retained Earnings
- 3200: Retained Earnings - Unappropriated
- 3300: Drawings/Dividends

#### Revenue (4 accounts)
- 4000: Sales Revenue
- 4200: Sales Returns and Allowances
- 4300: Sales Discounts
- 4400: Other Income

#### Expenses (5 accounts)
- 5000: Cost of Goods Sold (Category)
- 5100: Direct Materials
- 5200: Direct Labor
- 5300: Overhead
- 6000: Income Tax Expense

**Total: 35 critical accounts**

---

### 3. VAT Monthly Closing Structure

**Purpose:** Implement proper Philippine BIR VAT accounting

**Daily Operations:**
- **Input Tax (1200)**: Record VAT paid on purchases
- **Output Tax (2100)**: Record VAT collected on company invoices

**Month-End Closing:**

**Scenario 1: Output Tax > Input Tax (Net VAT Payable)**
```
Dr. Output Tax (2100)           12,000
    Cr. Input Tax (1200)                   10,000
    Cr. VAT Payable (2105)                  2,000
(To close monthly VAT - amount payable to BIR)
```

**Scenario 2: Input Tax > Output Tax (Excess Input Tax)**
```
Dr. Output Tax (2100)            8,000
Dr. Excess Input Tax Carry Over (1220)  2,000
    Cr. Input Tax (1200)                   10,000
(To close monthly VAT - excess to carry over)
```

**Key Accounts:**
- **1200 - Input Tax**: Daily VAT on purchases (cleared monthly)
- **1220 - Excess Input Tax Carry Over**: Excess input VAT (asset)
- **2100 - Output Tax**: Daily VAT on sales (cleared monthly)
- **2105 - VAT Payable**: Net monthly VAT liability to BIR

**Documentation:**
- Created `VAT_ACCOUNTS_EXPLANATION.md` with detailed examples
- Includes complete monthly cycle walkthrough
- BIR Form 2550M filing references

---

### 4. Manufacturing Cost Structure

**Changed from:** Single Cost of Goods Sold account

**Changed to:** Category structure with components

**Accounts:**
- **5000 - Cost of Goods Sold**: Category/Parent account
- **5100 - Direct Materials**: Raw materials used in production
- **5200 - Direct Labor**: Labor directly attributable to manufacturing
- **5300 - Overhead**: Manufacturing overhead costs

**Rationale:**
- Proper manufacturing cost accounting
- Aligns with Philippine SME practices
- Enables detailed cost analysis
- Supports job costing and process costing

---

### 5. BIR Compliance Accounts

**All required Philippine BIR accounts are now present:**

✓ Input Tax (1200)
✓ Creditable Withholding Tax (1210)
✓ Output Tax (2100)
✓ VAT Payable (2105)
✓ Withholding Tax Payable - Expanded (2110)
✓ Withholding Tax Payable - Compensation (2120)
✓ SSS Payable (2200)
✓ PhilHealth Payable (2210)
✓ Pag-IBIG Payable (2220)

**BIR Forms Supported:**
- Form 2550M (Monthly VAT Declaration)
- Form 1601C (Monthly Withholding Tax)
- Form 2316 (Certificate of Compensation Payment/Tax Withheld)
- SSS/PhilHealth/Pag-IBIG remittance forms

---

### 6. Documentation Created

**New Files:**
- `CHANGELOG.md` - This file
- `CRITICAL_ACCOUNTS.md` - Complete chart of accounts documentation
- `VAT_ACCOUNTS_EXPLANATION.md` - VAT monthly closing procedures
- `test_timezone.py` - Philippine timezone verification script
- `verify_accounts.py` - Account verification script

**Updated Files:**
- `app/fixtures.py` - Comprehensive fixture documentation

---

### 7. Database Migration

**Migration File:**
- `migrations/versions/3e45ac7ada83_.py` - Migration after timezone changes

**Previous Migration Removed:**
- `migrations/versions/5f9a82f6dd58_initial_migration_with_all_tables.py` - Superseded

**Scripts Available:**
- `init_db.py` - Initialize fresh database with fixtures
- `recreate_db_with_migrations.py` - Clean database recreation
- `load_fixtures.py` - Load fixtures to existing database

---

### 8. Bug Fixes

**Issue:** `NameError: name 'datetime' is not defined` in login view

**Root Cause:** After converting to Philippine Standard Time, removed `datetime` import but missed three references to `datetime.utcnow()` in failed login tracking.

**Fixed in:** `app/users/views.py`

**Locations Fixed:**
- Line 45: Failed login - invalid password
- Line 57: Failed login - invalid username
- Line 78: Failed login - inactive account

**Changed from:**
```python
login_time=datetime.utcnow(),
```

**Changed to:**
```python
login_time=ph_now(),
```

**Result:** All login tracking now properly uses Philippine Standard Time

---

### 9. Testing & Verification

**Timezone Testing:**
```bash
python test_timezone.py
```
**Results:**
- Current Philippine Time: 2026-06-01 06:05:30+08:00
- UTC Offset: +0800 (8 hours ahead of UTC)
- All model defaults verified: ✓

**Account Verification:**
```bash
python verify_accounts.py
```
**Results:**
- 35 critical accounts loaded
- All BIR compliance accounts present
- Proper account type distribution verified

---

### 10. Impact Summary

**Before:**
- Timestamps in UTC (incorrect for Philippine operations)
- Generic sample chart of accounts
- No VAT monthly closing structure
- Simple COGS without component breakdown

**After:**
- All timestamps in Philippine Standard Time (UTC+8)
- 35 critical accounts for Philippine SME operations
- Proper VAT monthly closing structure for BIR compliance
- Manufacturing cost structure (Direct Materials, Labor, Overhead)
- Complete BIR statutory deduction accounts
- Comprehensive documentation

**Benefits:**
1. **Accurate Time Tracking**: All audit trails, login history, and timestamps show Philippine local time
2. **BIR Compliance Ready**: All necessary accounts for Philippine tax compliance
3. **Manufacturing Support**: Proper cost accounting for manufacturing businesses
4. **Professional Structure**: Industry-standard chart of accounts
5. **VAT Automation Ready**: Structure supports automated monthly VAT closing
6. **Multi-Business Support**: Accounts support trading, manufacturing, and service businesses

---

### Technical Notes

**Philippine Standard Time (PST/PHT):**
- Timezone: Asia/Manila
- UTC Offset: +08:00 (no daylight saving time)
- Implementation: `timezone(timedelta(hours=8))`

**Database Considerations:**
- All datetime columns now store timezone-aware datetimes
- SQLite stores as ISO 8601 strings with timezone
- Migrations preserve existing data

**Performance Impact:**
- Minimal - timezone conversion happens at model level
- No additional database queries
- Template rendering unchanged

---

### Migration Path

**For Fresh Installation:**
```bash
flask db upgrade
python load_fixtures.py
```

**For Existing Database:**
```bash
# Backup current database
cp cas.db cas.db.backup

# Apply migration
flask db upgrade

# Reload fixtures (idempotent - safe to run)
python load_fixtures.py
```

**For Complete Recreation:**
```bash
python recreate_db_with_migrations.py
```

---

### Configuration

**No configuration changes required.**

All timezone settings are hardcoded to Philippine Standard Time as this application is specifically designed for Philippine businesses and BIR compliance.

**Environment Variables:** None required for timezone functionality

**Settings:** All managed through `app/utils.py` constants

---

### Future Considerations

**Potential Enhancements:**
1. Automated monthly VAT closing function
2. BIR form generation (2550M, 1601C)
3. Statutory deduction calculation utilities
4. Multi-currency support (if needed for foreign transactions)
5. Timezone-aware reporting filters

**Maintenance:**
- Monitor Philippine timezone changes (unlikely - no DST)
- Update BIR account codes if regulations change
- Review account structure annually

---

### Developer Notes

**When adding new models:**
```python
from app.utils import ph_now

class NewModel(db.Model):
    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
```

**When recording datetime in views:**
```python
from app.utils import ph_now

# Good
timestamp = ph_now()

# Bad - DO NOT USE
timestamp = datetime.now()  # Wrong timezone
timestamp = datetime.utcnow()  # Wrong timezone
```

**Template access:**
```jinja2
{# Current Philippine time available as 'now' #}
{{ now }}  {# Already in Philippine time #}
{{ now.strftime('%B %d, %Y %I:%M %p') }}
```

---

### Version Information

**Commit:** [To be generated]
**Date:** 2026-06-01
**Author:** Claude Code
**Branch:** main
**Tag:** v1.1.0-pht-critical-accounts

---

### Acknowledgments

This update implements Philippine business best practices and BIR compliance requirements for SME accounting systems.

**References:**
- BIR Tax Code and Regulations
- Philippine Accounting Standards
- BIR Revenue Memorandum Circulars on VAT
- Standard Manufacturing Cost Accounting Practices
