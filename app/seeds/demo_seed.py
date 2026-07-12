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
from app.common.vat_nature import resolve_sales_nature, resolve_purchase_nature
from app.seeds.statutory_2026 import seed_statutory_2026

TWO = Decimal('0.01')


def _money(x):
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


# code, name, type, parent, normal_balance
#
# NOTE: This is the DEMO-ONLY construction chart. It uses the flat legacy types and its
# codes are keyed to the demo transactions built below (seed-demo). The CANONICAL
# production construction COA is app/seeds/construction_coa.py (rich FS taxonomy, seeded
# via `flask seed-construction`). New construction *clients* get that one, not this demo chart.
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
    {'key': 'sv_print_form', 'value': 'current'},
    {'key': 'cd_print_access', 'value': 'draft_and_posted'},
    {'key': 'cd_check_print_access', 'value': 'draft_and_posted'},
    {'key': 'cr_print_access', 'value': 'draft_and_posted'},
    {'key': 'company_logo', 'value': ''},
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
        from app.seeds.seed_data import resolve_seed_admin_password
        pw = resolve_seed_admin_password()
        admin.set_password(pw)
        db.session.add(admin)
        db.session.commit()
        print(f"  [OK] Demo admin password: {pw} (shown once)")

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

    from app.posting.control_accounts import assign_default_control_accounts
    assign_default_control_accounts(updated_by='seed')

    # VAT (input) categories wired to Input VAT accounts
    if VATCategory.query.count() == 0:
        vat_acct = {a.code: a.id for a in Account.query.filter(
            Account.code.in_(['10501', '10502', '10503', '10504'])).all()}
        for c in [
            {'code': 'VEX',   'name': 'VAT Exempt',              'rate':  0.00, 'nature': 'exempt',            'acct': None},
            {'code': 'V0',    'name': 'VAT Zero-Rated',          'rate':  0.00, 'nature': 'zero_rated',        'acct': None},
            {'code': 'INV',   'name': 'Invalid',                 'rate':  0.00, 'nature': 'not_qualified',     'acct': None},
            {'code': 'V12CG', 'name': 'Input Tax Capital Goods', 'rate': 12.00, 'nature': 'capital_goods',     'acct': '10501'},
            {'code': 'V12DG', 'name': 'Input Tax Domestic Goods','rate': 12.00, 'nature': 'domestic_goods',    'acct': '10502'},
            {'code': 'V12SV', 'name': 'Input Tax Services',      'rate': 12.00, 'nature': 'domestic_services', 'acct': '10503'},
            {'code': 'V12IM', 'name': 'Input Tax Importation',   'rate': 12.00, 'nature': 'importation',       'acct': '10504'},
        ]:
            db.session.add(VATCategory(code=c['code'], name=c['name'], rate=c['rate'],
                                       description='', transaction_nature=c['nature'], is_active=True,
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
    # Open every month from Jan 2025 through Jun 2026 (the demo's full span).
    py, pm = 2025, 1
    while (py, pm) <= (2026, 6):
        AccountingPeriod.get_or_create_period(py, pm)
        pm += 1
        if pm > 12:
            pm, py = 1, py + 1

    # Seed 2026 statutory payroll tables (SSS, PhilHealth, Pag-IBIG, TRAIN WHT)
    seed_statutory_2026()

    return {'admin': admin, 'branch': branch}


# code, name, vat ('V12' VATable / 'VEX' non-VAT), wht (sales-side code or None)
CUSTOMERS = [
    {'code': 'C001', 'name': 'Vista Land Estates Inc.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C002', 'name': 'Megabuild Properties Corp.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C003', 'name': "St. Luke's Realty Development Corp.", 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C004', 'name': 'Ayala Township Development Inc.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C005', 'name': 'Robinsons Land Corporation', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C006', 'name': 'Greenfield District Devt Corp.', 'vat': 'V12', 'wht': 'WC120'},
    {'code': 'C007', 'name': 'Juan dela Cruz', 'vat': 'VEX', 'wht': None},
]

# code, name, vat (purchase category), wht, expense_code (default GL line account)
VENDORS = [
    {'code': 'V001', 'name': 'Holcim Philippines Inc.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V002', 'name': 'SteelAsia Manufacturing Corp.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V003', 'name': 'Wilcon Depot Inc.', 'vat': 'V12DG', 'wht': 'WC158', 'expense_code': '50101'},
    {'code': 'V004', 'name': 'Premier Electrical Subcontractor', 'vat': 'V12SV', 'wht': 'WC120', 'expense_code': '50103'},
    {'code': 'V005', 'name': 'Reliable Plumbing & Sanitary Subcon', 'vat': 'V12SV', 'wht': 'WC120', 'expense_code': '50103'},
    {'code': 'V006', 'name': 'Manila Equipment Rentals Inc.', 'vat': 'V12SV', 'wht': 'WC100', 'expense_code': '50104'},
    {'code': 'V007', 'name': 'Meralco', 'vat': 'V12SV', 'wht': None, 'expense_code': '50221'},
    {'code': 'V008', 'name': 'Petron Corporation', 'vat': 'V12DG', 'wht': None, 'expense_code': '50280'},
    {'code': 'V009', 'name': 'Cruz & Associates Law Office', 'vat': 'V12SV', 'wht': 'WC010', 'expense_code': '50240'},
    {'code': 'V010', 'name': 'Pioneer Insurance & Surety Corp.', 'vat': 'V12SV', 'wht': 'WC160', 'expense_code': '50298'},
]


def _wht(code):
    from app.withholding_tax.models import WithholdingTax
    return WithholdingTax.query.filter_by(code=code).first() if code else None


def seed_demo_customers(admin_id):
    from app.customers.models import Customer
    out = []
    for i, spec in enumerate(CUSTOMERS):
        c = Customer.query.filter_by(code=spec['code']).first()
        if c is None:
            c = Customer(code=spec['code'], name=spec['name'],
                         tin=f"{200 + i}-100-200-000",
                         address='Metro Manila', payment_terms='Net 60',
                         default_vat_category=spec['vat'], default_wt_code=spec['wht'],
                         is_active=True, created_by_id=admin_id)
            db.session.add(c)
        wt = _wht(spec['wht'])
        c.withholding_taxes = [wt] if wt else []
        out.append(c)
    db.session.commit()
    return out


def seed_demo_vendors():
    from app.vendors.models import Vendor
    out = []
    for i, spec in enumerate(VENDORS):
        v = Vendor.query.filter_by(code=spec['code']).first()
        if v is None:
            v = Vendor(code=spec['code'], name=spec['name'],
                       tin=f"{300 + i}-400-500-000",
                       payment_terms='Net 30', default_vat_category=spec['vat'],
                       is_active=True)
            db.session.add(v)
        wt = _wht(spec['wht'])
        v.withholding_taxes = [wt] if wt else []
        out.append(v)
    db.session.commit()
    return out


def resolve_refs():
    """Resolve the GL accounts the generators post against. Raises if missing."""
    def need(code):
        a = Account.query.filter_by(code=code).first()
        if a is None:
            raise RuntimeError(f"Required account {code} missing — run seed_demo_baseline first.")
        return a
    return {
        'ar': need('10201'),
        'cwt': need('10212'),
        'ap': need('20101'),
        'wt_payable': need('20301'),
        'output_vat': need('20401'),
        'cash_on_hand': need('10101'),
        'cash_bank': need('10111'),
        'revenue_contract': need('40101'),
        'revenue_rental': need('40201'),
        'cip': need('10310'),
        'equipment': need('11110'),
        'accum_dep_equipment': need('11111'),
        'dep_expense': need('50260'),
        'capital_stock': need('30101'),
        'apic': need('30102'),
        'expense': {code: need(code) for code in
                    ['50101', '50103', '50104', '50221', '50280', '50240', '50298', '50230']},
    }


def next_doc_number(prefix, doc_date, counters):
    """PREFIX-YYYY-MM-NNNN, sequencing per (prefix, year, month) on the DOC date."""
    key = (prefix, doc_date.year, doc_date.month)
    counters[key] = counters.get(key, 0) + 1
    return f'{prefix}-{doc_date.year}-{doc_date.month:02d}-{counters[key]:04d}'


def si_number(counters):
    counters[('SI',)] = counters.get(('SI',), 0) + 1
    return f"{counters[('SI',)]:05d}"


def crv_number(counters):
    counters[('CRV',)] = counters.get(('CRV',), 0) + 1
    return f"{counters[('CRV',)]:05d}"


def build_apv(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters):
    """Create one posted Accounts Payable (single line) + balanced posted JE."""
    from datetime import date as _date
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    from app.accounts_payable.views import _post_ap_je
    from app.utils import ph_now

    vatable = vendor_spec['vat'].startswith('V12')
    wt = _wht(vendor_spec['wht'])
    apnum = next_doc_number('AP', doc_date, counters)

    ap = AccountsPayable(
        branch_id=branch_id,
        ap_number=apnum,
        ap_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 30),
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        vendor_invoice_number=f'SI-{doc_date.year}{doc_date.month:02d}-{apnum[-4:]}',
        vendor_invoice_date=doc_date,
        payment_terms='Net 30',
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    item = AccountsPayableItem(
        line_number=1,
        description=f'{vendor_obj.name} — {doc_date.strftime("%b %Y")}',
        amount=_money(gross_amount),
        vat_category=vendor_spec['vat'],
        vat_nature=resolve_purchase_nature(vendor_spec['vat']),
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()
    ap.line_items.append(item)
    ap.calculate_totals()
    db.session.add(ap)
    db.session.flush()
    je = _post_ap_je(ap, admin_id)
    ap.journal_entry_id = je.id
    db.session.commit()
    return ap


def build_si(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    """Create one posted Sales Invoice (single line) + balanced posted JE."""
    from datetime import date as _date
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_invoices.views import _post_invoice_je
    from app.utils import ph_now

    vatable = customer_obj.default_vat_category == 'V12'
    wt = _wht('WC120') if vatable else None

    si = SalesInvoice(
        branch_id=branch_id,
        invoice_number=si_number(counters),
        invoice_date=doc_date,
        due_date=_date.fromordinal(doc_date.toordinal() + 60),
        customer_id=customer_obj.id,
        customer_name=customer_obj.name,
        customer_tin=customer_obj.tin,
        customer_address=customer_obj.address,
        status='posted',
        amount_paid=Decimal('0.00'),
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    item = SalesInvoiceItem(
        line_number=1,
        description='Progress billing — construction works',
        amount=_money(gross_amount),
        vat_category='V12' if vatable else 'VEX',
        vat_nature=resolve_sales_nature('V12' if vatable else 'VEX'),
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['revenue_contract'].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    item.calculate_amounts()   # extract VAT + WHT-on-net-of-rounded-VAT
    si.line_items.append(item)
    si.calculate_totals()
    db.session.add(si)
    db.session.flush()
    je = _post_invoice_je(si, admin_id)
    si.journal_entry_id = je.id
    db.session.commit()
    return si


def _new_crv(doc_date, customer_obj, refs, admin_id, branch_id, counters, method):
    from app.cash_receipts.models import CashReceiptVoucher
    from app.utils import ph_now
    cash = refs['cash_bank'] if method == 'check' else refs['cash_on_hand']
    crv = CashReceiptVoucher(
        branch_id=branch_id,
        crv_number=crv_number(counters),
        crv_date=doc_date,
        customer_id=customer_obj.id,
        customer_name=customer_obj.name,
        customer_tin=customer_obj.tin,
        payment_method=method,
        cash_account_id=cash.id,
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        crv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters.get(("CRV",), 0):04d}'
        crv.check_date = doc_date
        crv.check_bank = 'BDO'
    return crv


def build_crv_collecting(doc_date, invoice, refs, admin_id, branch_id, counters, method='check'):
    from app.cash_receipts.models import CRVArLine
    from app.cash_receipts.views import _post_crv_je, _apply_ar_collections
    crv = _new_crv(doc_date, invoice.customer, refs, admin_id, branch_id, counters, method)
    crv.ar_lines.append(CRVArLine(
        line_number=1,
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        original_balance=invoice.balance,
        amount_applied=_money(invoice.balance),
    ))
    crv.calculate_totals()
    db.session.add(crv)
    db.session.flush()
    je = _post_crv_je(crv, admin_id)
    crv.journal_entry_id = je.id
    _apply_ar_collections(crv)
    db.session.commit()
    return crv


def build_crv_revenue(doc_date, customer_obj, gross_amount, refs, admin_id, branch_id, counters):
    from app.cash_receipts.models import CRVRevenueLine
    from app.cash_receipts.views import _post_crv_je
    crv = _new_crv(doc_date, customer_obj, refs, admin_id, branch_id, counters, 'cash')
    line = CRVRevenueLine(
        line_number=1,
        description='Equipment rental income',
        amount=_money(gross_amount),
        vat_category='V12',
        vat_nature=resolve_sales_nature('V12'),
        vat_rate=Decimal('12.00'),
        account_id=refs['revenue_rental'].id,
        wt_rate=Decimal('0.00'),
    )
    line.calculate_amounts()
    crv.revenue_lines.append(line)
    crv.calculate_totals()
    db.session.add(crv)
    db.session.flush()
    je = _post_crv_je(crv, admin_id)
    crv.journal_entry_id = je.id
    db.session.commit()
    return crv


def _new_cdv(doc_date, vendor_obj, refs, admin_id, branch_id, counters, method):
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.utils import ph_now
    cash = refs['cash_bank'] if method == 'check' else refs['cash_on_hand']
    cdv = CashDisbursementVoucher(
        branch_id=branch_id,
        cdv_number=next_doc_number('CD', doc_date, counters),
        cdv_date=doc_date,
        vendor_id=vendor_obj.id,
        vendor_name=vendor_obj.name,
        vendor_tin=vendor_obj.tin,
        payment_method=method,
        cash_account_id=cash.id,
        notes='',
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    if method == 'check':
        cdv.check_number = f'{doc_date.year}{doc_date.month:02d}{counters[("CD", doc_date.year, doc_date.month)]:04d}'
        cdv.check_date = doc_date
        cdv.check_bank = 'BDO'
    return cdv


def build_cdv_paying(doc_date, ap, refs, admin_id, branch_id, counters, method='check'):
    from app.cash_disbursements.models import CDVApLine
    from app.cash_disbursements.views import _post_cdv_je, _apply_ap_payments
    cdv = _new_cdv(doc_date, ap.vendor, refs, admin_id, branch_id, counters, method)
    cdv.ap_lines.append(CDVApLine(
        line_number=1,
        ap_id=ap.id,
        ap_number=ap.ap_number,
        original_balance=ap.balance,
        amount_applied=_money(ap.balance),
    ))
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, admin_id)
    cdv.journal_entry_id = je.id
    _apply_ap_payments(cdv)
    db.session.commit()
    return cdv


def build_cdv_expense(doc_date, vendor_obj, vendor_spec, gross_amount, refs, admin_id, branch_id, counters, method='cash'):
    from app.cash_disbursements.models import CDVExpenseLine
    from app.cash_disbursements.views import _post_cdv_je
    vatable = vendor_spec['vat'].startswith('V12')
    wt = _wht(vendor_spec['wht'])
    cdv = _new_cdv(doc_date, vendor_obj, refs, admin_id, branch_id, counters, method)
    line = CDVExpenseLine(
        line_number=1,
        description=f'{vendor_obj.name} — {doc_date.strftime("%b %Y")}',
        amount=_money(gross_amount),
        vat_category=vendor_spec['vat'],
        vat_nature=resolve_purchase_nature(vendor_spec['vat']),
        vat_rate=Decimal('12.00') if vatable else Decimal('0.00'),
        account_id=refs['expense'][vendor_spec['expense_code']].id,
        wt_id=wt.id if wt else None,
        wt_rate=Decimal(str(wt.rate)) if wt else Decimal('0.00'),
    )
    line.calculate_amounts()
    cdv.expense_lines.append(line)
    cdv.calculate_totals()
    db.session.add(cdv)
    db.session.flush()
    je = _post_cdv_je(cdv, admin_id)
    cdv.journal_entry_id = je.id
    db.session.commit()
    return cdv


def _generate_jv_number(doc_date, branch_id):
    """JV-YYYY-MM-NNNN keyed to doc_date (not today) for historical seeding.

    Company-wide sequence -- `entry_number` is globally unique, so a per-branch
    sequence collides across branches.
    """
    from app.journal_entries.utils import next_sequence_number
    return next_sequence_number(f'JV-{doc_date.year}-{doc_date.month:02d}-')


def build_jv(doc_date, lines, refs, admin_id, branch_id, *,
             entry_type='adjustment', description, reference=''):
    """Create one posted Journal Voucher. lines = [(Account, debit, credit), ...]."""
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.utils import ph_now

    je = JournalEntry(
        entry_number=_generate_jv_number(doc_date, branch_id),
        entry_date=doc_date,
        description=description,
        reference=reference,
        entry_type=entry_type,
        branch_id=branch_id,
        status='posted',
        created_by_id=admin_id,
        posted_by_id=admin_id,
        posted_at=ph_now(),
    )
    for i, (acct, dr, cr) in enumerate(lines, start=1):
        je.lines.append(JournalEntryLine(
            line_number=i, account_id=acct.id,
            debit_amount=_money(dr), credit_amount=_money(cr),
            description=description,
        ))
    db.session.add(je)
    db.session.flush()
    je.calculate_totals()   # sets total_debit/credit/is_balanced
    if not je.is_balanced:
        raise ValueError(f"Journal voucher not balanced: {je.entry_number} (debit {je.total_debit} != credit {je.total_credit})")
    db.session.commit()
    return je


def seed_stockholder_investments(refs, admin_id, branch_id):
    """Three opening equity contributions (2 cash, 1 in-kind equipment)."""
    from datetime import date
    out = []
    # Wei Zhang — cash: 5,000,000 (4,000,000 par + 1,000,000 premium)
    out.append(build_jv(date(2025, 1, 2), [
        (refs['cash_bank'], Decimal('5000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('4000000.00')),
        (refs['apic'], Decimal('0.00'), Decimal('1000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Wei Zhang (cash)'))
    # Liang Chen — cash: 3,000,000 par
    out.append(build_jv(date(2025, 1, 2), [
        (refs['cash_bank'], Decimal('3000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('3000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Liang Chen (cash)'))
    # Mei Lin — in-kind: construction equipment 2,000,000 par
    out.append(build_jv(date(2025, 1, 3), [
        (refs['equipment'], Decimal('2000000.00'), Decimal('0.00')),
        (refs['capital_stock'], Decimal('0.00'), Decimal('2000000.00')),
    ], refs, admin_id, branch_id, entry_type='opening',
        description='Stockholder investment — Mei Lin (construction equipment, in-kind)'))
    return out


def _clamp_day(year, month, day, end):
    last = calendar.monthrange(year, month)[1]
    return min(date(year, month, min(day, last)), end)


def _count_unbalanced_jes():
    from app.journal_entries.models import JournalEntry
    bad = 0
    for je in JournalEntry.query.filter_by(status='posted').all():
        d = sum((l.debit_amount for l in je.lines.all()), Decimal('0.00'))
        c = sum((l.credit_amount for l in je.lines.all()), Decimal('0.00'))
        if d != c:
            bad += 1
    return bad


def generate_demo_transactions(refs, admin_id, branch_id, *, end=date(2026, 6, 19),
                               rng_seed=20250101):
    """Generate the Jan 1 2025 - Jun 19 2026 document set. Deterministic."""
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    rng = random.Random(rng_seed)
    counters = {}
    summary = {'si': 0, 'ap': 0, 'crv': 0, 'cdv': 0, 'jv': 0, 'unbalanced': 0}

    custs = [c for c in (Customer.query.filter_by(code=s['code']).first() for s in CUSTOMERS) if c]
    vends = {v.code: v for v in Vendor.query.all()}
    vatable_custs = [c for c in custs if c.default_vat_category == 'V12']

    # Stockholder investments first (opening equity)
    seed_stockholder_investments(refs, admin_id, branch_id)
    summary['jv'] += 3

    posted_sis, posted_aps = [], []
    # Every month from Jan 2025 through end's month (clamp keeps the final month <= end).
    months = []
    _y, _m = 2025, 1
    while (_y, _m) <= (end.year, end.month):
        months.append((_y, _m))
        _m += 1
        if _m > 12:
            _m, _y = 1, _y + 1
    for (y, m) in months:
        # ~2 SIs / month (skip days past end via clamp)
        for _ in range(2):
            cust = rng.choice(vatable_custs)
            d = _clamp_day(y, m, rng.randint(5, 20), end)
            if d > end:
                continue
            gross = _money(rng.uniform(300000, 900000))
            si = build_si(d, cust, gross, refs, admin_id, branch_id, counters)
            posted_sis.append(si)
            summary['si'] += 1
        # ~2 APs / month
        for _ in range(2):
            spec = rng.choice(VENDORS)
            vobj = vends[spec['code']]
            d = _clamp_day(y, m, rng.randint(3, 18), end)
            if d > end:
                continue
            gross = _money(rng.uniform(80000, 350000))
            ap = build_apv(d, vobj, spec, gross, refs, admin_id, branch_id, counters)
            posted_aps.append(ap)
            summary['ap'] += 1
        # depreciation JV each month
        d = _clamp_day(y, m, 28, end)
        build_jv(d, [(refs['dep_expense'], Decimal('25000.00'), Decimal('0.00')),
                     (refs['accum_dep_equipment'], Decimal('0.00'), Decimal('25000.00'))],
                 refs, admin_id, branch_id, entry_type='adjustment',
                 description=f'Monthly depreciation {d.strftime("%b %Y")}')
        summary['jv'] += 1

    # Collections / payments engineered for a realistic AGING SPREAD.
    # Pay (almost) everything, but deliberately leave a few docs unpaid in EACH
    # aging bucket so the AR/AP aging report populates Current / 1-30 / 31-60 /
    # 61-90 and a small 90+ tail — not 100% in 90+. Buckets are measured by due
    # date relative to `end` (the build is shown ~`end`, which is what the report
    # ages against). Selection is deterministic (first-N per bucket in gen order).
    from collections import defaultdict

    def _bucket(due_date):
        days = (end - due_date).days
        if days <= 0:
            return 'current'
        if days <= 30:
            return '1-30'
        if days <= 60:
            return '31-60'
        if days <= 90:
            return '61-90'
        return '90+'

    def _pick_unpaid(docs, targets):
        by_bucket = defaultdict(list)
        for d in docs:
            by_bucket[_bucket(d.due_date)].append(d)
        unpaid = set()
        for bucket, want in targets.items():
            for d in by_bucket.get(bucket, [])[:want]:
                unpaid.add(d.id)
        return unpaid

    # Want a believable profile: a little in each near-term bucket, a modest 90+ tail.
    _targets = {'current': 2, '1-30': 2, '31-60': 2, '61-90': 2, '90+': 3}
    unpaid_si = _pick_unpaid(posted_sis, _targets)
    unpaid_ap = _pick_unpaid(posted_aps, _targets)

    # Collect every SI except the deliberately-unpaid set (full collection)
    for si in posted_sis:
        if si.id in unpaid_si:
            continue
        pay = min(date.fromordinal(si.invoice_date.toordinal() + rng.randint(20, 40)), end)
        if pay >= si.invoice_date:
            build_crv_collecting(pay, si, refs, admin_id, branch_id, counters,
                                 method='check' if rng.random() < 0.6 else 'cash')
            summary['crv'] += 1
    # Pay every AP except the deliberately-unpaid set (full payment)
    for ap in posted_aps:
        if ap.id in unpaid_ap:
            continue
        pay = min(date.fromordinal(ap.ap_date.toordinal() + rng.randint(15, 35)), end)
        if pay >= ap.ap_date:
            build_cdv_paying(pay, ap, refs, admin_id, branch_id, counters,
                             method='check' if rng.random() < 0.6 else 'cash')
            summary['cdv'] += 1

    # A couple direct-revenue CRVs and direct-expense CDVs for variety
    build_crv_revenue(date(2025, 4, 15), vatable_custs[0], _money('56000.00'),
                      refs, admin_id, branch_id, counters)
    summary['crv'] += 1
    for spec_code, day, mon in [('V007', 10, 2), ('V008', 12, 5)]:
        spec = next(s for s in VENDORS if s['code'] == spec_code)
        build_cdv_expense(_clamp_day(2025, mon, day, end), vends[spec_code], spec,
                          _money(rng.uniform(8000, 40000)), refs, admin_id, branch_id, counters)
        summary['cdv'] += 1

    # A reclassification JV + a reversal-style JV for variety
    build_jv(date(2025, 6, 18),
             [(refs['cip'], Decimal('120000.00'), Decimal('0.00')),
              (refs['expense']['50101'], Decimal('0.00'), Decimal('120000.00'))],
             refs, admin_id, branch_id, entry_type='reclassification',
             description='Reclassify materials to CIP')
    summary['jv'] += 1

    summary['unbalanced'] = _count_unbalanced_jes()
    return summary


def run_seed_demo(reset=False):
    """Optionally reset, build baseline + master data + transactions. Returns summary."""
    if reset:
        db.drop_all()
        db.create_all()
    refs0 = seed_demo_baseline()
    seed_demo_customers(refs0['admin'].id)
    seed_demo_vendors()
    refs = resolve_refs()
    from app.sales_invoices.models import SalesInvoice
    if not reset and SalesInvoice.query.count() > 0:
        raise RuntimeError(
            "Demo transactions already present in this database. "
            "To rebuild: delete the DB file, run `flask db upgrade`, then `flask seed-demo`. "
            "(Refusing to add duplicates — invoice/AP numbers are unique.)"
        )
    return generate_demo_transactions(refs, refs0['admin'].id, refs0['branch'].id)
