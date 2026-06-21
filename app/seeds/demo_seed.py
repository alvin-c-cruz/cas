"""CAS demo-data generator — Zhiyuan Construction Corporation.

Builds documents and posts them through the real posting helpers so every
journal entry balances exactly like a hand-entered voucher. Mirrors
app/seeds/history_seed.py. See
docs/superpowers/specs/2026-06-21-cas-demo-database-design.md.
"""
import calendar
import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.accounts.models import Account

TWO = Decimal('0.01')


def _money(x):
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


# code, name, type, parent, normal_balance
CONSTRUCTION_COA = [
    # ---- ASSETS ----
    {'code': '10000', 'name': 'CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'nb': 'debit'},
    {'code': '10101', 'name': 'Cash on Hand', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10102', 'name': 'Petty Cash Fund', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10111', 'name': 'Cash in Bank - Current Account', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10112', 'name': 'Cash in Bank - Savings Account', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10201', 'name': 'Accounts Receivable - Trade', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10203', 'name': 'Retention Receivable', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10210', 'name': 'Advances to Subcontractors/Suppliers', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10212', 'name': 'Creditable Withholding Tax Receivable', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10301', 'name': 'Construction Materials Inventory', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10310', 'name': 'Construction in Progress (CIP)', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10500', 'name': 'Input VAT', 'type': 'Asset', 'parent': '10000', 'nb': 'debit'},
    {'code': '10501', 'name': 'Input VAT - Capital Goods', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10502', 'name': 'Input VAT - Domestic Goods', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10503', 'name': 'Input VAT - Services', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '10504', 'name': 'Input VAT - Importation', 'type': 'Asset', 'parent': '10500', 'nb': 'debit'},
    {'code': '11000', 'name': 'NON-CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'nb': 'debit'},
    {'code': '11110', 'name': 'Construction Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11111', 'name': 'Accumulated Depreciation - Construction Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11120', 'name': 'Vehicles', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11121', 'name': 'Accumulated Depreciation - Vehicles', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11130', 'name': 'Tools and Small Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11131', 'name': 'Accumulated Depreciation - Tools and Small Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    {'code': '11140', 'name': 'Office Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'debit'},
    {'code': '11141', 'name': 'Accumulated Depreciation - Office Equipment', 'type': 'Asset', 'parent': '11000', 'nb': 'credit'},
    # ---- LIABILITIES ----
    {'code': '20000', 'name': 'CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'nb': 'credit'},
    {'code': '20101', 'name': 'Accounts Payable - Trade', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20110', 'name': 'Subcontractors Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20120', 'name': 'Retention Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20300', 'name': 'Withholding Tax Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20301', 'name': 'Withholding Tax Payable - Expanded', 'type': 'Liability', 'parent': '20300', 'nb': 'credit'},
    {'code': '20302', 'name': 'Withholding Tax Payable - Compensation', 'type': 'Liability', 'parent': '20300', 'nb': 'credit'},
    {'code': '20401', 'name': 'Output VAT Payable', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20420', 'name': 'Statutory Payables', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '20421', 'name': 'SSS Premiums Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20422', 'name': 'PhilHealth Contributions Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20423', 'name': 'Pag-IBIG Contributions Payable', 'type': 'Liability', 'parent': '20420', 'nb': 'credit'},
    {'code': '20430', 'name': 'Billings in Excess of Costs', 'type': 'Liability', 'parent': '20000', 'nb': 'credit'},
    {'code': '21000', 'name': 'NON-CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'nb': 'credit'},
    {'code': '21101', 'name': 'Loans Payable', 'type': 'Liability', 'parent': '21000', 'nb': 'credit'},
    # ---- EQUITY ----
    {'code': '30000', 'name': 'EQUITY', 'type': 'Equity', 'parent': None, 'nb': 'credit'},
    {'code': '30101', 'name': 'Capital Stock', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30102', 'name': 'Additional Paid-in Capital', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30103', 'name': 'Subscriptions Receivable', 'type': 'Equity', 'parent': '30000', 'nb': 'debit'},
    {'code': '30201', 'name': 'Retained Earnings', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    {'code': '30301', 'name': 'Current-Year Earnings', 'type': 'Equity', 'parent': '30000', 'nb': 'credit'},
    # ---- REVENUE ----
    {'code': '40000', 'name': 'REVENUE', 'type': 'Revenue', 'parent': None, 'nb': 'credit'},
    {'code': '40101', 'name': 'Construction Contract Revenue', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40102', 'name': 'Service Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40103', 'name': 'Materials Sales', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40201', 'name': 'Equipment Rental Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40202', 'name': 'Interest Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    {'code': '40203', 'name': 'Miscellaneous Income', 'type': 'Revenue', 'parent': '40000', 'nb': 'credit'},
    # ---- COST OF CONSTRUCTION ----
    {'code': '50100', 'name': 'Cost of Construction', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50101', 'name': 'Direct Materials', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50102', 'name': 'Direct Labor', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50103', 'name': 'Subcontractor Costs', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50104', 'name': 'Equipment Rental Expense', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50105', 'name': 'Permits and Project Fees', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    {'code': '50106', 'name': 'Project Overhead', 'type': 'Expense', 'parent': '50100', 'nb': 'debit'},
    # ---- OPERATING EXPENSES ----
    {'code': '50200', 'name': 'Operating Expenses', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50210', 'name': 'Salaries and Wages', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50211', 'name': 'Employee Benefits', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50220', 'name': 'Rent Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50221', 'name': 'Utilities - Electricity', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50222', 'name': 'Utilities - Water', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50223', 'name': 'Communications', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50230', 'name': 'Office Supplies Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50240', 'name': 'Professional Fees', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50250', 'name': 'Taxes and Licenses', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50260', 'name': 'Depreciation Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50270', 'name': 'Repairs and Maintenance', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50280', 'name': 'Fuel and Oil', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50290', 'name': 'Representation and Entertainment', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50298', 'name': 'Miscellaneous Expense', 'type': 'Expense', 'parent': '50200', 'nb': 'debit'},
    {'code': '50300', 'name': 'Financial Expenses', 'type': 'Expense', 'parent': None, 'nb': 'debit'},
    {'code': '50301', 'name': 'Interest Expense', 'type': 'Expense', 'parent': '50300', 'nb': 'debit'},
    {'code': '50302', 'name': 'Bank Charges', 'type': 'Expense', 'parent': '50300', 'nb': 'debit'},
]


def seed_construction_coa():
    """Create the construction COA (two-pass). Idempotent; returns count created."""
    if Account.query.count() > 0:
        return 0
    by_code = {}
    for a in CONSTRUCTION_COA:
        acct = Account(code=a['code'], name=a['name'], account_type=a['type'],
                       normal_balance=a['nb'], is_active=True)
        db.session.add(acct)
        by_code[a['code']] = acct
    db.session.flush()  # assign ids
    for a in CONSTRUCTION_COA:
        if a['parent']:
            by_code[a['code']].parent_id = by_code[a['parent']].id
    db.session.commit()
    return len(CONSTRUCTION_COA)
