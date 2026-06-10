"""
Database seeding functions.

This module provides functions to seed the database with initial data
required for the application to function properly.

Usage:
    flask seed-db
    or
    flask seed-db --force  # To reseed even if data exists
"""

from app import db
from app.users.models import User
from app.branches.models import Branch
from app.accounts.models import Account
from app.vat_categories.models import VATCategory
from app.withholding_tax.models import WithholdingTax
from app.settings import AppSettings
from datetime import datetime


def seed_admin_user():
    """
    Seed default administrator user.

    Credentials:
        Username: admin
        Password: ac1123581321
        Role: admin
    """
    # Check if admin already exists
    admin = User.query.filter_by(username='admin').first()

    if admin:
        print("  [SKIP] Admin user already exists, skipping...")
        return False

    # Create admin user
    admin = User(
        username='admin',
        email='admin@cascorp.ph',
        full_name='System Administrator',
        role='admin',
        is_active=True
    )
    admin.set_password('ac1123581321')

    db.session.add(admin)
    db.session.commit()

    print("  [OK] Admin user created (username: admin, password: ac1123581321)")
    return True


def seed_default_branch():
    """
    Seed default Main Branch.

    This is required for the application to function as all transactions
    are associated with a branch.
    """
    # Check if Main Branch already exists
    main_branch = Branch.query.filter_by(code='MAIN').first()

    if main_branch:
        print("  [SKIP] Main Branch already exists, skipping...")
        return False

    # Create Main Branch
    main_branch = Branch(
        code='MAIN',
        name='Main Branch',
        address='Head Office',
        is_active=True
    )

    db.session.add(main_branch)
    db.session.commit()

    print("  [OK] Main Branch created (code: MAIN)")
    return True


def seed_chart_of_accounts():
    """
    Seed complete Chart of Accounts following Philippine BIR requirements.

    Account Types:
    - 1xxxx: Assets
    - 2xxxx: Liabilities
    - 3xxxx: Equity
    - 4xxxx: Revenue
    - 5xxxx: Expenses
    """
    # Check if accounts already exist
    existing_count = Account.query.count()

    if existing_count > 0:
        print(f"  [SKIP] {existing_count} accounts already exist, skipping...")
        return False

    accounts = [
        # ======================
        # ASSETS (1xxxx)
        # ======================

        # Current Assets (10xxx)
        {'code': '10000', 'name': 'CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'is_header': True},

        # Cash and Bank Accounts
        {'code': '10100', 'name': 'Cash and Cash Equivalents', 'type': 'Asset', 'parent': '10000', 'is_header': True},
        {'code': '10101', 'name': 'Cash on Hand', 'type': 'Asset', 'parent': '10100', 'normal_balance': 'debit'},
        {'code': '10102', 'name': 'Petty Cash Fund', 'type': 'Asset', 'parent': '10100', 'normal_balance': 'debit'},
        {'code': '10110', 'name': 'Cash in Bank - Current Account', 'type': 'Asset', 'parent': '10100', 'normal_balance': 'debit'},
        {'code': '10111', 'name': 'Cash in Bank - Savings Account', 'type': 'Asset', 'parent': '10100', 'normal_balance': 'debit'},
        {'code': '10112', 'name': 'Cash in Bank - Payroll Account', 'type': 'Asset', 'parent': '10100', 'normal_balance': 'debit'},

        # Accounts Receivable
        {'code': '10200', 'name': 'Accounts Receivable', 'type': 'Asset', 'parent': '10000', 'is_header': True},
        {'code': '10201', 'name': 'Accounts Receivable - Trade', 'type': 'Asset', 'parent': '10200', 'normal_balance': 'debit'},
        {'code': '10202', 'name': 'Allowance for Doubtful Accounts', 'type': 'Asset', 'parent': '10200', 'normal_balance': 'credit'},
        {'code': '10210', 'name': 'Other Receivables', 'type': 'Asset', 'parent': '10200', 'normal_balance': 'debit'},
        {'code': '10211', 'name': 'Advances to Employees', 'type': 'Asset', 'parent': '10200', 'normal_balance': 'debit'},

        # Inventory
        {'code': '10300', 'name': 'Inventory', 'type': 'Asset', 'parent': '10000', 'is_header': True},
        {'code': '10301', 'name': 'Merchandise Inventory', 'type': 'Asset', 'parent': '10300', 'normal_balance': 'debit'},
        {'code': '10302', 'name': 'Office Supplies Inventory', 'type': 'Asset', 'parent': '10300', 'normal_balance': 'debit'},

        # Prepaid Expenses
        {'code': '10400', 'name': 'Prepaid Expenses', 'type': 'Asset', 'parent': '10000', 'is_header': True},
        {'code': '10401', 'name': 'Prepaid Rent', 'type': 'Asset', 'parent': '10400', 'normal_balance': 'debit'},
        {'code': '10402', 'name': 'Prepaid Insurance', 'type': 'Asset', 'parent': '10400', 'normal_balance': 'debit'},

        # Input VAT
        {'code': '10500', 'name': 'Input VAT', 'type': 'Asset', 'parent': '10000', 'is_header': True},
        {'code': '10501', 'name': 'Input VAT - Current', 'type': 'Asset', 'parent': '10500', 'normal_balance': 'debit'},
        {'code': '10502', 'name': 'Input VAT - Deferred', 'type': 'Asset', 'parent': '10500', 'normal_balance': 'debit'},

        # Non-Current Assets (11xxx)
        {'code': '11000', 'name': 'NON-CURRENT ASSETS', 'type': 'Asset', 'parent': None, 'is_header': True},

        # Property, Plant & Equipment
        {'code': '11100', 'name': 'Property, Plant and Equipment', 'type': 'Asset', 'parent': '11000', 'is_header': True},
        {'code': '11101', 'name': 'Land', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11102', 'name': 'Building', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11103', 'name': 'Accumulated Depreciation - Building', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'credit'},
        {'code': '11110', 'name': 'Furniture and Fixtures', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11111', 'name': 'Accumulated Depreciation - Furniture and Fixtures', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'credit'},
        {'code': '11120', 'name': 'Office Equipment', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11121', 'name': 'Accumulated Depreciation - Office Equipment', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'credit'},
        {'code': '11130', 'name': 'Computer Equipment', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11131', 'name': 'Accumulated Depreciation - Computer Equipment', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'credit'},
        {'code': '11140', 'name': 'Vehicles', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'debit'},
        {'code': '11141', 'name': 'Accumulated Depreciation - Vehicles', 'type': 'Asset', 'parent': '11100', 'normal_balance': 'credit'},

        # ======================
        # LIABILITIES (2xxxx)
        # ======================

        # Current Liabilities (20xxx)
        {'code': '20000', 'name': 'CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'is_header': True},

        # Accounts Payable
        {'code': '20100', 'name': 'Accounts Payable', 'type': 'Liability', 'parent': '20000', 'is_header': True},
        {'code': '20101', 'name': 'Accounts Payable - Trade', 'type': 'Liability', 'parent': '20100', 'normal_balance': 'credit'},
        {'code': '20102', 'name': 'Accounts Payable - Others', 'type': 'Liability', 'parent': '20100', 'normal_balance': 'credit'},

        # Output VAT
        {'code': '20200', 'name': 'Output VAT', 'type': 'Liability', 'parent': '20000', 'is_header': True},
        {'code': '20201', 'name': 'Output VAT - Sales', 'type': 'Liability', 'parent': '20200', 'normal_balance': 'credit'},

        # Withholding Taxes Payable
        {'code': '20300', 'name': 'Withholding Taxes Payable', 'type': 'Liability', 'parent': '20000', 'is_header': True},
        {'code': '20301', 'name': 'Withholding Tax Payable - Expanded', 'type': 'Liability', 'parent': '20300', 'normal_balance': 'credit'},
        {'code': '20302', 'name': 'Withholding Tax Payable - Compensation', 'type': 'Liability', 'parent': '20300', 'normal_balance': 'credit'},

        # Other Taxes Payable
        {'code': '20400', 'name': 'Other Taxes Payable', 'type': 'Liability', 'parent': '20000', 'is_header': True},
        {'code': '20401', 'name': 'Income Tax Payable', 'type': 'Liability', 'parent': '20400', 'normal_balance': 'credit'},
        {'code': '20402', 'name': 'SSS Contributions Payable', 'type': 'Liability', 'parent': '20400', 'normal_balance': 'credit'},
        {'code': '20403', 'name': 'PhilHealth Contributions Payable', 'type': 'Liability', 'parent': '20400', 'normal_balance': 'credit'},
        {'code': '20404', 'name': 'Pag-IBIG Contributions Payable', 'type': 'Liability', 'parent': '20400', 'normal_balance': 'credit'},

        # Accrued Expenses
        {'code': '20500', 'name': 'Accrued Expenses', 'type': 'Liability', 'parent': '20000', 'is_header': True},
        {'code': '20501', 'name': 'Accrued Salaries and Wages', 'type': 'Liability', 'parent': '20500', 'normal_balance': 'credit'},
        {'code': '20502', 'name': 'Accrued Interest Payable', 'type': 'Liability', 'parent': '20500', 'normal_balance': 'credit'},

        # Non-Current Liabilities (21xxx)
        {'code': '21000', 'name': 'NON-CURRENT LIABILITIES', 'type': 'Liability', 'parent': None, 'is_header': True},
        {'code': '21101', 'name': 'Long-term Loans Payable', 'type': 'Liability', 'parent': '21000', 'normal_balance': 'credit'},

        # ======================
        # EQUITY (3xxxx)
        # ======================

        {'code': '30000', 'name': 'EQUITY', 'type': 'Equity', 'parent': None, 'is_header': True},
        {'code': '30101', 'name': 'Capital Stock', 'type': 'Equity', 'parent': '30000', 'normal_balance': 'credit'},
        {'code': '30201', 'name': 'Retained Earnings', 'type': 'Equity', 'parent': '30000', 'normal_balance': 'credit'},
        {'code': '30301', 'name': 'Current Year Earnings', 'type': 'Equity', 'parent': '30000', 'normal_balance': 'credit'},
        {'code': '30401', 'name': 'Drawings/Dividends', 'type': 'Equity', 'parent': '30000', 'normal_balance': 'debit'},

        # ======================
        # REVENUE (4xxxx)
        # ======================

        {'code': '40000', 'name': 'REVENUE', 'type': 'Revenue', 'parent': None, 'is_header': True},

        # Sales Revenue
        {'code': '40100', 'name': 'Sales Revenue', 'type': 'Revenue', 'parent': '40000', 'is_header': True},
        {'code': '40101', 'name': 'Sales - Goods', 'type': 'Revenue', 'parent': '40100', 'normal_balance': 'credit'},
        {'code': '40102', 'name': 'Sales - Services', 'type': 'Revenue', 'parent': '40100', 'normal_balance': 'credit'},
        {'code': '40103', 'name': 'Sales Returns and Allowances', 'type': 'Revenue', 'parent': '40100', 'normal_balance': 'debit'},
        {'code': '40104', 'name': 'Sales Discounts', 'type': 'Revenue', 'parent': '40100', 'normal_balance': 'debit'},

        # Other Income
        {'code': '40200', 'name': 'Other Income', 'type': 'Revenue', 'parent': '40000', 'is_header': True},
        {'code': '40201', 'name': 'Interest Income', 'type': 'Revenue', 'parent': '40200', 'normal_balance': 'credit'},
        {'code': '40202', 'name': 'Rental Income', 'type': 'Revenue', 'parent': '40200', 'normal_balance': 'credit'},
        {'code': '40203', 'name': 'Miscellaneous Income', 'type': 'Revenue', 'parent': '40200', 'normal_balance': 'credit'},

        # ======================
        # EXPENSES (5xxxx)
        # ======================

        {'code': '50000', 'name': 'EXPENSES', 'type': 'Expense', 'parent': None, 'is_header': True},

        # Cost of Sales
        {'code': '50100', 'name': 'Cost of Sales', 'type': 'Expense', 'parent': '50000', 'is_header': True},
        {'code': '50101', 'name': 'Cost of Goods Sold', 'type': 'Expense', 'parent': '50100', 'normal_balance': 'debit'},
        {'code': '50102', 'name': 'Purchases', 'type': 'Expense', 'parent': '50100', 'normal_balance': 'debit'},
        {'code': '50103', 'name': 'Purchase Returns and Allowances', 'type': 'Expense', 'parent': '50100', 'normal_balance': 'credit'},
        {'code': '50104', 'name': 'Purchase Discounts', 'type': 'Expense', 'parent': '50100', 'normal_balance': 'credit'},

        # Operating Expenses
        {'code': '50200', 'name': 'Operating Expenses', 'type': 'Expense', 'parent': '50000', 'is_header': True},

        # Salaries and Wages
        {'code': '50210', 'name': 'Salaries and Wages Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50211', 'name': 'Employee Benefits Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50212', 'name': 'SSS Contributions Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50213', 'name': 'PhilHealth Contributions Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50214', 'name': 'Pag-IBIG Contributions Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Rent and Utilities
        {'code': '50220', 'name': 'Rent Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50221', 'name': 'Utilities Expense - Electricity', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50222', 'name': 'Utilities Expense - Water', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50223', 'name': 'Utilities Expense - Telephone and Internet', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Office and Supplies
        {'code': '50230', 'name': 'Office Supplies Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50231', 'name': 'Stationery and Printing', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Professional Fees
        {'code': '50240', 'name': 'Professional Fees', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50241', 'name': 'Legal Fees', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50242', 'name': 'Accounting and Audit Fees', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Taxes and Licenses
        {'code': '50250', 'name': 'Taxes and Licenses', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50251', 'name': 'Business Permits and Licenses', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50252', 'name': 'Local Business Tax', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Depreciation
        {'code': '50260', 'name': 'Depreciation Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Repairs and Maintenance
        {'code': '50270', 'name': 'Repairs and Maintenance', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Transportation and Travel
        {'code': '50280', 'name': 'Transportation and Travel', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50281', 'name': 'Fuel and Oil', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Marketing and Advertising
        {'code': '50290', 'name': 'Marketing and Advertising', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Insurance
        {'code': '50295', 'name': 'Insurance Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Miscellaneous Expenses
        {'code': '50298', 'name': 'Miscellaneous Expenses', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},
        {'code': '50299', 'name': 'Bad Debts Expense', 'type': 'Expense', 'parent': '50200', 'normal_balance': 'debit'},

        # Financial Expenses
        {'code': '50300', 'name': 'Financial Expenses', 'type': 'Expense', 'parent': '50000', 'is_header': True},
        {'code': '50301', 'name': 'Interest Expense', 'type': 'Expense', 'parent': '50300', 'normal_balance': 'debit'},
        {'code': '50302', 'name': 'Bank Charges', 'type': 'Expense', 'parent': '50300', 'normal_balance': 'debit'},
    ]

    # Create accounts in two passes
    # Pass 1: Create all accounts without parent relationships
    account_map = {}
    for acc_data in accounts:
        account = Account(
            code=acc_data['code'],
            name=acc_data['name'],
            account_type=acc_data['type'],
            normal_balance=acc_data.get('normal_balance', 'debit' if acc_data['type'] in ['Asset', 'Expense'] else 'credit'),
            is_active=True
        )
        db.session.add(account)
        account_map[acc_data['code']] = account

    db.session.flush()  # Get IDs assigned

    # Pass 2: Set parent relationships
    for acc_data in accounts:
        parent_code = acc_data.get('parent')
        if parent_code and parent_code in account_map:
            account_map[acc_data['code']].parent_id = account_map[parent_code].id

    db.session.commit()

    print(f"  [OK] {len(accounts)} accounts created in Chart of Accounts")
    return True


def seed_vat_categories():
    """
    Seed VAT categories following Philippine BIR requirements.
    """
    # Check if VAT categories already exist
    existing_count = VATCategory.query.count()

    if existing_count > 0:
        print(f"  [SKIP] {existing_count} VAT categories already exist, skipping...")
        return False

    vat_categories = [
        {'code': 'VATABLE', 'name': 'Vatable (12%)', 'rate': 12.00, 'description': 'Standard VAT rate'},
        {'code': 'VAT-EXEMPT', 'name': 'VAT-Exempt', 'rate': 0.00, 'description': 'Transactions exempt from VAT'},
        {'code': 'ZERO-RATED', 'name': 'Zero-Rated', 'rate': 0.00, 'description': 'Zero-rated transactions (exports, etc.)'},
        {'code': 'NON-VAT', 'name': 'Non-VAT', 'rate': 0.00, 'description': 'Non-VAT transactions'},
    ]

    for cat_data in vat_categories:
        vat_cat = VATCategory(
            code=cat_data['code'],
            name=cat_data['name'],
            rate=cat_data['rate'],
            description=cat_data['description'],
            is_active=True
        )
        db.session.add(vat_cat)

    db.session.commit()

    print(f"  [OK] {len(vat_categories)} VAT categories created")
    return True


def seed_withholding_tax_codes():
    """
    Seed common withholding tax codes following Philippine BIR requirements.
    """
    # Check if withholding tax codes already exist
    existing_count = WithholdingTax.query.count()

    if existing_count > 0:
        print(f"  [SKIP] {existing_count} withholding tax codes already exist, skipping...")
        return False

    wt_codes = [
        # Expanded Withholding Tax (EWT)
        {'code': 'WC010', 'name': 'Professional Fees', 'description': 'EWT - Professional Fees', 'rate': 10.00},
        {'code': 'WC020', 'name': 'Professional Fees to General Professional Partnerships', 'description': 'EWT - Professional Fees to GPP', 'rate': 10.00},
        {'code': 'WC030', 'name': 'Income Payments to Certain Professionals', 'description': 'EWT - Certain Professionals', 'rate': 5.00},
        {'code': 'WC040', 'name': 'Rental Income - Real Property', 'description': 'EWT - Real Property Rental', 'rate': 5.00},
        {'code': 'WC050', 'name': 'Rental Income - Personal Property', 'description': 'EWT - Personal Property Rental', 'rate': 5.00},
        {'code': 'WC060', 'name': 'Income Payment to Contractors', 'description': 'EWT - Contractors', 'rate': 2.00},
        {'code': 'WC070', 'name': 'Income Payment for Services', 'description': 'EWT - Services', 'rate': 2.00},
        {'code': 'WC080', 'name': 'Commission', 'description': 'EWT - Commission', 'rate': 10.00},
        {'code': 'WC090', 'name': 'Tolling Fees', 'description': 'EWT - Tolling Fees', 'rate': 5.00},
        {'code': 'WC100', 'name': 'Interest from Bank Deposits', 'description': 'EWT - Bank Interest', 'rate': 20.00},
    ]

    for wt_data in wt_codes:
        wt_code = WithholdingTax(
            code=wt_data['code'],
            name=wt_data['name'],
            description=wt_data['description'],
            rate=wt_data['rate'],
            is_active=True
        )
        db.session.add(wt_code)

    db.session.commit()

    print(f"  [OK] {len(wt_codes)} withholding tax codes created")
    return True


def seed_app_settings():
    """
    Seed default application settings.
    """
    # Check if app settings already exist
    existing_count = AppSettings.query.count()

    if existing_count > 0:
        print(f"  [SKIP] App settings already exist, skipping...")
        return False

    settings = [
        {'key': 'company_name', 'value': 'My Company'},
        {'key': 'company_tin', 'value': ''},
        {'key': 'company_address', 'value': ''},
        {'key': 'fiscal_year_start', 'value': '01'},
    ]

    for setting_data in settings:
        setting = AppSettings(
            key=setting_data['key'],
            value=setting_data['value'],
            updated_by='system'
        )
        db.session.add(setting)

    db.session.commit()

    print(f"  [OK] {len(settings)} app settings created")
    return True


def seed_all(force=False):
    """
    Seed all initial data.

    Args:
        force (bool): If True, will delete existing data and reseed.
                     Use with caution in production!

    Returns:
        dict: Summary of seeding operations
    """
    print("\n" + "="*60)
    print("DATABASE SEEDING")
    print("="*60 + "\n")

    if force:
        print("[SKIP] FORCE MODE: This will delete existing data!\n")
        # Note: Implement force delete logic if needed

    results = {
        'admin_user': False,
        'main_branch': False,
        'chart_of_accounts': False,
        'vat_categories': False,
        'withholding_tax_codes': False,
        'app_settings': False,
    }

    try:
        print("1. Seeding Administrator User...")
        results['admin_user'] = seed_admin_user()

        print("\n2. Seeding Default Branch...")
        results['main_branch'] = seed_default_branch()

        print("\n3. Seeding Chart of Accounts...")
        results['chart_of_accounts'] = seed_chart_of_accounts()

        print("\n4. Seeding VAT Categories...")
        results['vat_categories'] = seed_vat_categories()

        print("\n5. Seeding Withholding Tax Codes...")
        results['withholding_tax_codes'] = seed_withholding_tax_codes()

        print("\n6. Seeding App Settings...")
        results['app_settings'] = seed_app_settings()

        print("\n" + "="*60)
        print("SEEDING COMPLETE!")
        print("="*60)

        # Summary
        seeded_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        print(f"\nSeeded: {seeded_count}/{total_count} categories")
        print("\nYou can now log in with:")
        print("  Username: admin")
        print("  Password: ac1123581321")
        print("\n")

        return results

    except Exception as e:
        print(f"\n[ERROR] Error during seeding: {str(e)}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    print("This module should be run via Flask CLI:")
    print("  flask seed-db")
