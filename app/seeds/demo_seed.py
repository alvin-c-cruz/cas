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


COMPANY_SETTINGS = [
    {'key': 'company_name', 'value': 'Zhiyuan Construction Corporation'},
    {'key': 'trade_name', 'value': 'Zhiyuan Construction'},
    {'key': 'company_tin', 'value': '456-789-123-000'},
    {'key': 'company_address', 'value': '12 Mindanao Avenue, Project 8, Quezon City, Metro Manila'},
    {'key': 'postal_code', 'value': '1106'},
    {'key': 'rdo_code', 'value': '039'},
    {'key': 'tin_branch_code', 'value': '000'},
    {'key': 'fiscal_year_start', 'value': '01'},
    {'key': 'email', 'value': 'info@zhiyuanconstruction.ph'},
    {'key': 'phone', 'value': '(02) 8123-4567'},
    {'key': 'vat_registration_type', 'value': 'VAT'},
    {'key': 'officer_president', 'value': 'Wei Zhang'},
    {'key': 'officer_treasurer', 'value': 'Liang Chen'},
    {'key': 'officer_secretary', 'value': 'Mei Lin'},
    {'key': 'apv_print_access', 'value': 'draft_and_posted'},
    {'key': 'sv_print_access', 'value': 'draft_and_posted'},
    {'key': 'cd_print_access', 'value': 'draft_and_posted'},
    {'key': 'cr_print_access', 'value': 'draft_and_posted'},
    {'key': 'company_logo', 'value': ''},
    {'key': 'environment', 'value': 'demo'},
]

# code, name, rate, sales_name (None = purchase-only)
WHT_CODES = [
    {'code': 'WC120', 'name': 'Contractors/Subcontractors', 'rate': 2.00,
     'sales_name': 'Construction/Contractor (2% CWT)'},
    {'code': 'WC158', 'name': 'Income payments - Goods', 'rate': 1.00,
     'sales_name': 'Sale of Goods (1% CWT)'},
    {'code': 'WC160', 'name': 'Income payments - Services', 'rate': 2.00,
     'sales_name': 'Sale of Services (2% CWT)'},
    {'code': 'WC100', 'name': 'Rentals', 'rate': 5.00, 'sales_name': None},
    {'code': 'WC010', 'name': 'Professional Fees', 'rate': 10.00, 'sales_name': None},
]


def seed_demo_baseline():
    """COA + admin + branch + settings + tax tables + 2025 periods. Idempotent."""
    from app.users.models import User
    from app.branches.models import Branch
    from app.settings import AppSettings
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.periods.models import AccountingPeriod

    seed_construction_coa()

    # Admin
    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        admin = User(username='admin', email='admin@zhiyuanconstruction.ph',
                     full_name='System Administrator', role='admin', is_active=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Branch + assignment
    branch = Branch.query.filter_by(code='MAIN').first()
    if branch is None:
        branch = Branch(code='MAIN', name='Main Branch', address='Head Office', is_active=True)
        db.session.add(branch)
        db.session.commit()
    if branch not in admin.branches.all():
        admin.branches.append(branch)
        db.session.commit()

    # Settings
    if AppSettings.query.count() == 0:
        for s in COMPANY_SETTINGS:
            db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
        db.session.commit()

    # VAT (input) categories wired to Input VAT accounts
    if VATCategory.query.count() == 0:
        vat_acct = {a.code: a.id for a in Account.query.filter(
            Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
        for c in [
            {'code': 'VEX', 'name': 'VAT Exempt', 'rate': 0.00, 'acct': None},
            {'code': 'V0', 'name': 'VAT Zero-Rated', 'rate': 0.00, 'acct': None},
            {'code': 'INV', 'name': 'Invalid', 'rate': 0.00, 'acct': None},
            {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'acct': '10501'},
            {'code': 'V12DG', 'name': 'Input Tax Domestic Goods', 'rate': 12.00, 'acct': '10502'},
            {'code': 'V12SV', 'name': 'Input Tax Services', 'rate': 12.00, 'acct': '10503'},
            {'code': 'V12IM', 'name': 'Input Tax Importation', 'rate': 12.00, 'acct': '10504'},
        ]:
            db.session.add(VATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                       description='', is_active=True,
                                       input_vat_account_id=vat_acct.get(c['acct']) if c['acct'] else None))
        db.session.commit()

    # Sales (output) VAT categories wired to Output VAT Payable (20401)
    if SalesVATCategory.query.count() == 0:
        out_id = Account.query.filter_by(code='20401').first().id
        for c in [
            {'code': 'V12', 'name': 'VATable Sales (12%)', 'rate': 12.00, 'nature': 'regular', 'acct': out_id},
            {'code': 'V0', 'name': 'VAT Zero-Rated Sales', 'rate': 0.00, 'nature': 'zero_export', 'acct': None},
            {'code': 'VEX', 'name': 'VAT-Exempt Sales', 'rate': 0.00, 'nature': 'exempt', 'acct': None},
        ]:
            db.session.add(SalesVATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                            transaction_nature=c['nature'],
                                            output_vat_account_id=c['acct'], is_active=True))
        db.session.commit()

    # WHT codes
    if WithholdingTax.query.count() == 0:
        for w in WHT_CODES:
            db.session.add(WithholdingTax(code=w['code'], name=w['name'], description='',
                                          rate=w['rate'], sales_name=w['sales_name'], is_active=True))
        db.session.commit()

    # Open 2025 Jan-Jun periods
    for m in range(1, 7):
        AccountingPeriod.get_or_create_period(2025, m)

    return {'admin': admin, 'branch': branch}
