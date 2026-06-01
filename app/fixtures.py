"""
Default data fixtures for database initialization

This module contains all default data that should be loaded when
initializing a fresh database.
"""
from app import db
from app.users.models import User
from app.accounts.models import Account
from app.branches.models import Branch
from app.settings import AppSettings


def load_default_admin():
    """Create default admin user."""
    if User.query.filter_by(username='admin').first():
        print("  [i] Admin user already exists, skipping...")
        return None

    admin = User(
        username='admin',
        email='admin@cas.local',
        full_name='System Administrator',
        role='admin',
        is_active=True
    )
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    print("  [OK] Default admin user created (username: admin, password: admin123)")
    return admin


def load_sample_chart_of_accounts():
    """
    Create critical chart of accounts for application functionality.

    These accounts are essential for the CAS system to function properly,
    including Philippine BIR compliance and core accounting operations.
    """
    if Account.query.count() > 0:
        print("  [i] Chart of accounts already populated, skipping...")
        return []

    critical_accounts = [
        # ========================================
        # ASSETS - Current Assets
        # ========================================
        Account(code='1000', name='Cash on Hand', account_type='Asset', classification='Current', normal_balance='Debit'),
        Account(code='1010', name='Cash in Bank', account_type='Asset', classification='Current', normal_balance='Debit'),

        # Accounts Receivable (CRITICAL for AR/invoicing)
        Account(code='1100', name='Accounts Receivable', account_type='Asset', classification='Current', normal_balance='Debit'),
        Account(code='1110', name='Allowance for Doubtful Accounts', account_type='Asset', classification='Current', normal_balance='Credit'),

        # BIR Compliance - Input Tax & Creditable Withholding Tax (CRITICAL for VAT/Withholding)
        Account(code='1200', name='Input Tax', account_type='Asset', classification='Current', normal_balance='Debit'),
        Account(code='1210', name='Creditable Withholding Tax', account_type='Asset', classification='Current', normal_balance='Debit'),
        Account(code='1220', name='Excess Input Tax Carry Over', account_type='Asset', classification='Current', normal_balance='Debit'),

        # Inventory
        Account(code='1300', name='Inventory', account_type='Asset', classification='Current', normal_balance='Debit'),
        Account(code='1400', name='Prepaid Expenses', account_type='Asset', classification='Current', normal_balance='Debit'),

        # ASSETS - Non-Current Assets
        Account(code='1500', name='Property, Plant and Equipment', account_type='Asset', classification='Non-Current', normal_balance='Debit'),
        Account(code='1510', name='Accumulated Depreciation', account_type='Asset', classification='Non-Current', normal_balance='Credit'),

        # ========================================
        # LIABILITIES - Current Liabilities
        # ========================================
        # Accounts Payable (CRITICAL for AP/bills)
        Account(code='2000', name='Accounts Payable', account_type='Liability', classification='Current', normal_balance='Credit'),

        # BIR Compliance - VAT & Withholding Taxes (CRITICAL)
        Account(code='2100', name='Output Tax', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2105', name='VAT Payable', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2110', name='Withholding Tax Payable - Expanded', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2120', name='Withholding Tax Payable - Compensation', account_type='Liability', classification='Current', normal_balance='Credit'),

        # Philippine Statutory Deductions (CRITICAL for Philippine payroll)
        Account(code='2200', name='SSS Payable', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2210', name='PhilHealth Payable', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2220', name='Pag-IBIG Payable', account_type='Liability', classification='Current', normal_balance='Credit'),

        # Other Current Liabilities
        Account(code='2300', name='Salaries and Wages Payable', account_type='Liability', classification='Current', normal_balance='Credit'),
        Account(code='2400', name='Accrued Expenses', account_type='Liability', classification='Current', normal_balance='Credit'),

        # LIABILITIES - Non-Current Liabilities
        Account(code='2500', name='Long-term Loans Payable', account_type='Liability', classification='Non-Current', normal_balance='Credit'),

        # ========================================
        # EQUITY (CRITICAL)
        # ========================================
        Account(code='3000', name='Capital Stock', account_type='Equity', classification='', normal_balance='Credit'),
        Account(code='3100', name='Retained Earnings', account_type='Equity', classification='', normal_balance='Credit'),
        Account(code='3200', name='Retained Earnings - Unappropriated', account_type='Equity', classification='', normal_balance='Credit'),
        Account(code='3300', name='Drawings/Dividends', account_type='Equity', classification='', normal_balance='Debit'),

        # ========================================
        # REVENUE (CRITICAL)
        # ========================================
        Account(code='4000', name='Sales Revenue', account_type='Revenue', classification='', normal_balance='Credit'),
        Account(code='4200', name='Sales Returns and Allowances', account_type='Revenue', classification='', normal_balance='Debit'),
        Account(code='4300', name='Sales Discounts', account_type='Revenue', classification='', normal_balance='Debit'),
        Account(code='4400', name='Other Income', account_type='Revenue', classification='', normal_balance='Credit'),

        # ========================================
        # EXPENSES (CRITICAL)
        # ========================================
        # Cost of Goods Sold (Category)
        Account(code='5000', name='Cost of Goods Sold', account_type='Expense', classification='', normal_balance='Debit'),
        Account(code='5100', name='Direct Materials', account_type='Expense', classification='', normal_balance='Debit'),
        Account(code='5200', name='Direct Labor', account_type='Expense', classification='', normal_balance='Debit'),
        Account(code='5300', name='Overhead', account_type='Expense', classification='', normal_balance='Debit'),

        # Other Expenses
        Account(code='6000', name='Income Tax Expense', account_type='Expense', classification='', normal_balance='Debit'),
    ]

    db.session.add_all(critical_accounts)
    db.session.commit()
    print(f"  [OK] Critical chart of accounts created ({len(critical_accounts)} accounts)")
    return critical_accounts


def load_default_branch():
    """Create default main branch."""
    if Branch.query.filter_by(code='MAIN').first():
        print("  [i] Main branch already exists, skipping...")
        return None

    main_branch = Branch(
        code='MAIN',
        name='Main Office',
        address='Main Office Address',
        phone='',
        email='',
        is_active=True
    )
    db.session.add(main_branch)
    db.session.commit()
    print("  [OK] Default 'Main Office' branch created")
    return main_branch


def load_default_settings():
    """Initialize default application settings."""
    settings_created = []

    # Environment setting
    if not AppSettings.query.filter_by(key='environment').first():
        AppSettings.set_setting('environment', 'dev', 'system')
        settings_created.append('environment')

    # Add more default settings here as needed
    # Example:
    # if not AppSettings.query.filter_by(key='company_name').first():
    #     AppSettings.set_setting('company_name', 'My Company', 'system')
    #     settings_created.append('company_name')

    if settings_created:
        print(f"  [OK] Default settings initialized: {', '.join(settings_created)}")
    else:
        print("  [i] Default settings already exist, skipping...")

    return settings_created


def load_sample_vendors():
    """Create sample vendors for demonstration."""
    from app.vendors.models import Vendor

    if Vendor.query.count() > 0:
        print("  [i] Vendors already exist, skipping...")
        return []

    sample_vendors = [
        Vendor(
            code='V001',
            name='Steel Supply Co.',
            contact_person='Pedro Dela Cruz',
            phone='09121234567',
            email='pedro@steelsupply.ph',
            tin='123-456-789-000',
            payment_terms='Net 30',
            address='123 Industrial Avenue, Quezon City',
            check_payee_name='Steel Supply Co.',
            postal_code='1100',
            default_vat_category='Other Goods (12%)',
            wt_wc158=True,
            is_active=True
        ),
        Vendor(
            code='V002',
            name='Office Depot Philippines',
            contact_person='Linda Santos',
            phone='09231234567',
            email='linda@officedepot.ph',
            tin='234-567-890-000',
            payment_terms='Net 15',
            address='456 Makati Avenue, Makati City',
            check_payee_name='Office Depot PH Inc.',
            postal_code='1200',
            default_vat_category='Other Goods (12%)',
            wt_wc158=True,
            is_active=True
        ),
        Vendor(
            code='V003',
            name='Manila Electric Company',
            contact_person='Ramon Garcia',
            phone='09341234567',
            email='ramon@meralco.ph',
            tin='345-678-901-000',
            payment_terms='Net 30',
            address='Lopez Building, Ortigas Center, Pasig City',
            check_payee_name='MERALCO',
            postal_code='1600',
            default_vat_category='Services (12%)',
            is_active=True
        ),
        Vendor(
            code='V004',
            name='Construction Supplies Inc.',
            contact_person='Teresa Bautista',
            phone='09451234567',
            email='teresa@constructionsupplies.ph',
            tin='456-789-012-000',
            payment_terms='Net 45',
            address='789 Caloocan Road, Caloocan City',
            check_payee_name='Construction Supplies Inc.',
            postal_code='1400',
            default_vat_category='Other Goods (12%)',
            wt_wc100=True,
            is_active=True
        ),
        Vendor(
            code='V005',
            name='Professional Maintenance Services',
            contact_person='Jose Mendoza',
            phone='09561234567',
            email='jose@promaintenance.ph',
            tin='567-890-123-000',
            payment_terms='Net 30',
            address='321 Taft Avenue, Manila',
            check_payee_name='Pro Maintenance Services',
            postal_code='1000',
            default_vat_category='Services (12%)',
            wt_wc010=True,
            is_active=True
        ),
    ]

    for vendor in sample_vendors:
        db.session.add(vendor)

    db.session.commit()
    print(f"  [OK] {len(sample_vendors)} sample vendors created")
    return sample_vendors


def load_all_fixtures():
    """
    Load all default fixtures.

    This function loads all default data in the correct order:
    1. Admin user
    2. Main branch
    3. Sample chart of accounts
    4. Sample vendors
    5. Application settings
    """
    print("\n" + "="*60)
    print("Loading Default Fixtures")
    print("="*60)

    print("\n1. Creating default admin user...")
    load_default_admin()

    print("\n2. Creating default branch...")
    load_default_branch()

    print("\n3. Loading sample chart of accounts...")
    load_sample_chart_of_accounts()

    print("\n4. Loading sample vendors...")
    load_sample_vendors()

    print("\n5. Initializing default settings...")
    load_default_settings()

    print("\n" + "="*60)
    print("[OK] All fixtures loaded successfully!")
    print("="*60 + "\n")


def reset_database():
    """
    WARNING: This will delete all data!

    Drops all tables and recreates them from migrations.
    Then loads default fixtures.
    """
    print("\n" + "!"*60)
    print("WARNING: This will DELETE ALL DATA in the database!")
    print("!"*60)

    response = input("\nAre you sure you want to continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Database reset cancelled.")
        return False

    print("\nDropping all tables...")
    db.drop_all()
    print("[OK] All tables dropped")

    print("\nCreating tables from migrations...")
    db.create_all()
    print("[OK] Tables created")

    print("\nLoading default fixtures...")
    load_all_fixtures()

    return True
