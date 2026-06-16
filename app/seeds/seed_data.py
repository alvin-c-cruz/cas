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

    # Map VAT-bearing categories to the seed COA's input VAT account
    # (seed_chart_of_accounts runs before this in seed_all)
    input_vat_acct = Account.query.filter_by(code='10501').first()
    input_vat_id = input_vat_acct.id if input_vat_acct else None

    vat_categories = [
        {'code': 'VATABLE', 'name': 'Vatable (12%)', 'rate': 12.00, 'description': 'Standard VAT rate', 'input_vat_account_id': input_vat_id},
        {'code': 'VAT-EXEMPT', 'name': 'VAT-Exempt', 'rate': 0.00, 'description': 'Transactions exempt from VAT', 'input_vat_account_id': None},
        {'code': 'ZERO-RATED', 'name': 'Zero-Rated', 'rate': 0.00, 'description': 'Zero-rated transactions (exports, etc.)', 'input_vat_account_id': None},
        {'code': 'NON-VAT', 'name': 'Non-VAT', 'rate': 0.00, 'description': 'Non-VAT transactions', 'input_vat_account_id': None},
    ]

    for cat_data in vat_categories:
        vat_cat = VATCategory(
            code=cat_data['code'],
            name=cat_data['name'],
            rate=cat_data['rate'],
            description=cat_data['description'],
            input_vat_account_id=cat_data['input_vat_account_id'],
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


def seed_minimal():
    """
    Seed a bare-minimum database for client demo/testing.

    Creates:
    - 1 admin user
    - 1 main branch (assigned to admin)
    - 17 app settings
    - 28 accounts (Assets, Liabilities, Equity, Revenue, Expenses with hierarchical structure)
    - 7 VAT categories (V12CG/V12DG/V12SV/V12IM/V0/VEX/INV)
    - 3 WHT codes (WC158, WC160, WC100)
    """
    print("\n" + "="*60)
    print("MINIMAL DATABASE SEEDING")
    print("="*60 + "\n")

    try:
        # ------------------------------------------------------------------
        # 1. Admin user
        # ------------------------------------------------------------------
        print("1. Seeding admin user...")
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print("  [SKIP] Admin user already exists")
        else:
            admin = User(
                username='admin',
                email='admin@cascorp.ph',
                full_name='System Administrator',
                role='admin',
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("  [OK] Admin user created (username: admin, password: admin123)")

        # ------------------------------------------------------------------
        # 2. Main Branch + assign admin
        # ------------------------------------------------------------------
        print("\n2. Seeding Main Branch...")
        main_branch = Branch.query.filter_by(code='MAIN').first()
        if main_branch:
            print("  [SKIP] Main Branch already exists")
        else:
            main_branch = Branch(
                code='MAIN',
                name='Main Branch',
                address='Head Office',
                is_active=True
            )
            db.session.add(main_branch)
            db.session.commit()
            print("  [OK] Main Branch created (code: MAIN)")

        # Assign admin to branch if not already assigned
        if main_branch not in admin.branches.all():
            admin.branches.append(main_branch)
            db.session.commit()
            print("  [OK] Admin assigned to Main Branch")

        # ------------------------------------------------------------------
        # 3. App settings
        # ------------------------------------------------------------------
        print("\n3. Seeding app settings...")
        existing_settings = AppSettings.query.count()
        if existing_settings > 0:
            print(f"  [SKIP] {existing_settings} app settings already exist")
        else:
            settings = [
                {'key': 'company_name',         'value': 'ABC Company'},
                {'key': 'company_tin',          'value': '123-456-789'},
                {'key': 'company_address',      'value': 'Unit 5, 123 Rizal Street, Poblacion, Makati City, Metro Manila'},
                {'key': 'fiscal_year_start',    'value': '01'},
                {'key': 'email',                'value': 'info@alvincruzaccounting.ph'},
                {'key': 'phone',                'value': '(02) 8765-4321'},
                {'key': 'postal_code',          'value': '1210'},
                {'key': 'rdo_code',             'value': '050'},
                {'key': 'tin_branch_code',      'value': '000'},
                {'key': 'trade_name',           'value': 'ACAS'},
                {'key': 'vat_registration_type','value': 'VAT'},
                {'key': 'officer_president',    'value': 'Alvin C. Cruz'},
                {'key': 'officer_secretary',    'value': 'Sofia Esperanza M. Cruz'},
                {'key': 'officer_treasurer',    'value': 'Joan Hazel M. Cruz'},
                {'key': 'apv_print_access',     'value': 'posted_only'},
                {'key': 'sv_print_access',      'value': 'posted_only'},
                {'key': 'cd_print_access',      'value': 'posted_only'},
            ]
            for s in settings:
                db.session.add(AppSettings(key=s['key'], value=s['value'], updated_by='system'))
            db.session.commit()
            print(f"  [OK] 17 app settings created")

        # ------------------------------------------------------------------
        # 4. Chart of Accounts (28 accounts, three-pass seed: parents, then children)
        # ------------------------------------------------------------------
        print("\n4. Seeding Chart of Accounts...")
        existing_accounts = Account.query.count()
        if existing_accounts > 0:
            print(f"  [SKIP] {existing_accounts} accounts already exist")
        else:
            # Pass 1: Root groups/standalones (no parent_id)
            pass1_accounts = [
                # Assets
                Account(code='10101', name='Cash on Hand',                account_type='Asset',     normal_balance='debit',  is_active=True),
                Account(code='10102', name='Cash in Bank',                account_type='Asset',     normal_balance='debit',  is_active=True),
                Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',     normal_balance='debit',  is_active=True),
                Account(code='10212', name='Creditable WHT Receivable',   account_type='Asset',     normal_balance='debit',  is_active=True),
                Account(code='10500', name='Input VAT',                   account_type='Asset',     normal_balance='debit',  is_active=True),
                # Liabilities
                Account(code='20101', name='Accounts Payable - Trade',    account_type='Liability', normal_balance='credit', is_active=True),
                Account(code='20300', name='Withholding Tax Payable',     account_type='Liability', normal_balance='credit', is_active=True),
                Account(code='20401', name='Output VAT Payable',          account_type='Liability', normal_balance='credit', is_active=True),
                # Equity
                Account(code='30100', name='Owner\'s Equity',             account_type='Equity',    normal_balance='credit', is_active=True),
                # Revenue
                Account(code='40000', name='Sales Revenue',               account_type='Revenue',   normal_balance='credit', is_active=True),
                # Expense
                Account(code='60100', name='Operating Expenses',          account_type='Expense',   normal_balance='debit',  is_active=True),
            ]
            db.session.add_all(pass1_accounts)
            db.session.flush()  # Assign IDs

            # Get parents by code for Pass 2
            parent_10500 = Account.query.filter_by(code='10500').first()
            parent_20300 = Account.query.filter_by(code='20300').first()
            parent_60100 = Account.query.filter_by(code='60100').first()

            # Pass 2: Children of 10500 (Input VAT) and 20300 (WHT Payable)
            pass2_accounts = [
                Account(code='10501', name='Input VAT - Capital Goods', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='10502', name='Input VAT - Domestic Goods', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='10503', name='Input VAT - Services', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='10504', name='Input VAT - Importation', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='10505', name='Excess Input Tax Carry-Over', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='10506', name='Deferred Input Tax', account_type='Asset', normal_balance='debit', is_active=True, parent_id=parent_10500.id),
                Account(code='20301', name='Withholding Tax Payable - Expanded', account_type='Liability', normal_balance='credit', is_active=True, parent_id=parent_20300.id),
            ]
            db.session.add_all(pass2_accounts)
            db.session.flush()  # Assign IDs

            # Pass 3: Children of 60100 (Operating Expenses)
            pass3_accounts = [
                Account(code='60101', name='Office Supplies Expense', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60102', name='Salaries and Wages', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60103', name='Rent Expense', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60104', name='Electricity and Water', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60105', name='Communications Expense', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60106', name='Transportation and Travel', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60107', name='Repairs and Maintenance', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60108', name='Representation and Entertainment', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60109', name='Professional Fees', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
                Account(code='60110', name='Miscellaneous Expense', account_type='Expense', normal_balance='debit', is_active=True, parent_id=parent_60100.id),
            ]
            db.session.add_all(pass3_accounts)
            db.session.commit()
            print("  [OK] 28 accounts created in Chart of Accounts")

        # ------------------------------------------------------------------
        # 5. VAT Categories
        # ------------------------------------------------------------------
        print("\n5. Seeding VAT categories...")
        existing_vat = VATCategory.query.count()
        if existing_vat > 0:
            print(f"  [SKIP] {existing_vat} VAT categories already exist")
        else:
            # Look up input VAT accounts and output VAT account (seeded above)
            vat_accounts = {
                a.code: a.id
                for a in Account.query.filter(Account.code.in_(
                    ['10501', '10502', '10503', '10504']
                )).all()
            }
            _output_vat = Account.query.filter_by(code='20401').first()
            output_vat_id = _output_vat.id if _output_vat else None

            vat_categories = [
                {'code': 'VEX',   'name': 'VAT Exempt',               'rate':  0.00, 'input_vat_account_id': None,                      'output_vat_account_id': None},
                {'code': 'V0',    'name': 'VAT Zero-Rated',            'rate':  0.00, 'input_vat_account_id': None,                      'output_vat_account_id': None},
                {'code': 'INV',   'name': 'Invalid',                   'rate':  0.00, 'input_vat_account_id': None,                      'output_vat_account_id': None},
                {'code': 'V12CG', 'name': 'Input Tax Capital Goods',   'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10501'), 'output_vat_account_id': output_vat_id},
                {'code': 'V12DG', 'name': 'Input Tax Domestic Goods',  'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10502'), 'output_vat_account_id': output_vat_id},
                {'code': 'V12SV', 'name': 'Input Tax Services',        'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10503'), 'output_vat_account_id': output_vat_id},
                {'code': 'V12IM', 'name': 'Input Tax Importation',     'rate': 12.00, 'input_vat_account_id': vat_accounts.get('10504'), 'output_vat_account_id': output_vat_id},
            ]
            for cat in vat_categories:
                db.session.add(VATCategory(
                    code=cat['code'],
                    name=cat['name'],
                    rate=cat['rate'],
                    description='',
                    input_vat_account_id=cat['input_vat_account_id'],
                    output_vat_account_id=cat['output_vat_account_id'],
                    is_active=True
                ))
            db.session.commit()
            print(f"  [OK] {len(vat_categories)} VAT categories created")

        # ------------------------------------------------------------------
        # 6. Withholding Tax Codes
        # ------------------------------------------------------------------
        print("\n6. Seeding withholding tax codes...")
        existing_wht = WithholdingTax.query.count()
        if existing_wht > 0:
            print(f"  [SKIP] {existing_wht} withholding tax codes already exist")
        else:
            wht_codes = [
                {'code': 'WC158', 'name': 'Withholding Tax - Goods',     'rate': 1.00},
                {'code': 'WC160', 'name': 'Withholding Tax - Services',   'rate': 2.00},
                {'code': 'WC100', 'name': 'Withholding Tax - Rentals',    'rate': 5.00},
            ]
            for wt in wht_codes:
                db.session.add(WithholdingTax(
                    code=wt['code'],
                    name=wt['name'],
                    description='',
                    rate=wt['rate'],
                    is_active=True
                ))
            db.session.commit()
            print(f"  [OK] {len(wht_codes)} withholding tax codes created")

        print("\n" + "="*60)
        print("MINIMAL SEEDING COMPLETE!")
        print("="*60)
        print("\nYou can now log in with:")
        print("  Username: admin")
        print("  Password: admin123")
        print("\n")

    except Exception as e:
        print(f"\n[ERROR] Error during minimal seeding: {str(e)}")
        db.session.rollback()
        raise


if __name__ == '__main__':
    print("This module should be run via Flask CLI:")
    print("  flask seed-db")
