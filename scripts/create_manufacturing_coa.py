"""
Script to create a comprehensive Chart of Accounts for a Manufacturing Company
"""
from app import create_app, db
from app.accounts.models import Account

app = create_app()

# Manufacturing Chart of Accounts Structure
manufacturing_coa = [
    # ASSETS
    # Current Assets
    {'code': '1000', 'name': 'Cash and Cash Equivalents', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': None},
    {'code': '1010', 'name': 'Cash on Hand', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1000'},
    {'code': '1020', 'name': 'Cash in Bank - Operating Account', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1000'},
    {'code': '1030', 'name': 'Cash in Bank - Payroll Account', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1000'},

    {'code': '1100', 'name': 'Accounts Receivable', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': None},
    {'code': '1110', 'name': 'Accounts Receivable - Trade', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1100'},
    {'code': '1120', 'name': 'Allowance for Doubtful Accounts', 'type': 'Asset', 'classification': 'Current', 'balance': 'Credit', 'parent': '1100'},

    {'code': '1200', 'name': 'Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': None},
    {'code': '1210', 'name': 'Raw Materials Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1200'},
    {'code': '1220', 'name': 'Work in Process Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1200'},
    {'code': '1230', 'name': 'Finished Goods Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1200'},
    {'code': '1240', 'name': 'Manufacturing Supplies Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1200'},
    {'code': '1250', 'name': 'Packaging Materials Inventory', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1200'},

    {'code': '1300', 'name': 'Prepaid Expenses', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': None},
    {'code': '1310', 'name': 'Prepaid Insurance', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1300'},
    {'code': '1320', 'name': 'Prepaid Rent', 'type': 'Asset', 'classification': 'Current', 'balance': 'Debit', 'parent': '1300'},

    # Fixed Assets (Property, Plant & Equipment)
    {'code': '1500', 'name': 'Property, Plant and Equipment', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': None},
    {'code': '1510', 'name': 'Land', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': '1500'},
    {'code': '1520', 'name': 'Buildings', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': '1500'},
    {'code': '1525', 'name': 'Accumulated Depreciation - Buildings', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '1500'},
    {'code': '1530', 'name': 'Manufacturing Equipment', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': '1500'},
    {'code': '1535', 'name': 'Accumulated Depreciation - Mfg Equipment', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '1500'},
    {'code': '1540', 'name': 'Office Equipment', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': '1500'},
    {'code': '1545', 'name': 'Accumulated Depreciation - Office Equipment', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '1500'},
    {'code': '1550', 'name': 'Vehicles', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Debit', 'parent': '1500'},
    {'code': '1555', 'name': 'Accumulated Depreciation - Vehicles', 'type': 'Asset', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '1500'},

    # LIABILITIES
    # Current Liabilities
    {'code': '2000', 'name': 'Accounts Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': None},
    {'code': '2010', 'name': 'Accounts Payable - Trade', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2000'},
    {'code': '2020', 'name': 'Accounts Payable - Suppliers', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2000'},

    {'code': '2100', 'name': 'Accrued Expenses', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': None},
    {'code': '2110', 'name': 'Salaries and Wages Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},
    {'code': '2120', 'name': 'SSS Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},
    {'code': '2130', 'name': 'PhilHealth Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},
    {'code': '2140', 'name': 'Pag-IBIG Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},
    {'code': '2150', 'name': 'Withholding Tax Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},
    {'code': '2160', 'name': 'Output VAT Payable', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2100'},

    {'code': '2200', 'name': 'Short-term Loans', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': None},
    {'code': '2210', 'name': 'Bank Loans - Short-term', 'type': 'Liability', 'classification': 'Current', 'balance': 'Credit', 'parent': '2200'},

    # Long-term Liabilities
    {'code': '2500', 'name': 'Long-term Liabilities', 'type': 'Liability', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': None},
    {'code': '2510', 'name': 'Bank Loans - Long-term', 'type': 'Liability', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '2500'},
    {'code': '2520', 'name': 'Mortgage Payable', 'type': 'Liability', 'classification': 'Non-Current', 'balance': 'Credit', 'parent': '2500'},

    # EQUITY
    {'code': '3000', 'name': 'Capital Stock', 'type': 'Equity', 'classification': None, 'balance': 'Credit', 'parent': None},
    {'code': '3010', 'name': 'Common Stock', 'type': 'Equity', 'classification': None, 'balance': 'Credit', 'parent': '3000'},
    {'code': '3020', 'name': 'Additional Paid-in Capital', 'type': 'Equity', 'classification': None, 'balance': 'Credit', 'parent': '3000'},

    {'code': '3100', 'name': 'Retained Earnings', 'type': 'Equity', 'classification': None, 'balance': 'Credit', 'parent': None},
    {'code': '3200', 'name': 'Dividends', 'type': 'Equity', 'classification': None, 'balance': 'Debit', 'parent': None},

    # REVENUE
    {'code': '4000', 'name': 'Sales Revenue', 'type': 'Revenue', 'classification': None, 'balance': 'Credit', 'parent': None},
    {'code': '4010', 'name': 'Sales - Finished Products', 'type': 'Revenue', 'classification': None, 'balance': 'Credit', 'parent': '4000'},
    {'code': '4020', 'name': 'Sales Returns and Allowances', 'type': 'Revenue', 'classification': None, 'balance': 'Debit', 'parent': '4000'},
    {'code': '4030', 'name': 'Sales Discounts', 'type': 'Revenue', 'classification': None, 'balance': 'Debit', 'parent': '4000'},

    {'code': '4100', 'name': 'Other Income', 'type': 'Revenue', 'classification': None, 'balance': 'Credit', 'parent': None},
    {'code': '4110', 'name': 'Interest Income', 'type': 'Revenue', 'classification': None, 'balance': 'Credit', 'parent': '4100'},
    {'code': '4120', 'name': 'Scrap Sales', 'type': 'Revenue', 'classification': None, 'balance': 'Credit', 'parent': '4100'},

    # COST OF GOODS SOLD
    {'code': '5000', 'name': 'Cost of Goods Sold', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},

    # Direct Materials
    {'code': '5100', 'name': 'Direct Materials', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '5110', 'name': 'Raw Materials Used', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5100'},
    {'code': '5120', 'name': 'Freight-in on Materials', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5100'},

    # Direct Labor
    {'code': '5200', 'name': 'Direct Labor', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '5210', 'name': 'Production Workers Salaries', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5200'},
    {'code': '5220', 'name': 'Production Workers Benefits', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5200'},

    # Manufacturing Overhead
    {'code': '5300', 'name': 'Manufacturing Overhead', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '5310', 'name': 'Indirect Materials', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5320', 'name': 'Indirect Labor', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5330', 'name': 'Factory Utilities', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5340', 'name': 'Factory Supplies', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5350', 'name': 'Factory Maintenance and Repairs', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5360', 'name': 'Depreciation - Manufacturing Equipment', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5370', 'name': 'Factory Rent', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},
    {'code': '5380', 'name': 'Factory Insurance', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '5300'},

    # OPERATING EXPENSES
    # Selling Expenses
    {'code': '6000', 'name': 'Selling Expenses', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '6010', 'name': 'Sales Salaries', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6000'},
    {'code': '6020', 'name': 'Sales Commissions', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6000'},
    {'code': '6030', 'name': 'Advertising and Promotion', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6000'},
    {'code': '6040', 'name': 'Delivery and Shipping Expense', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6000'},
    {'code': '6050', 'name': 'Marketing Expense', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6000'},

    # Administrative Expenses
    {'code': '6100', 'name': 'Administrative Expenses', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '6110', 'name': 'Office Salaries', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6120', 'name': 'Office Supplies', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6130', 'name': 'Office Rent', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6140', 'name': 'Office Utilities', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6150', 'name': 'Professional Fees', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6160', 'name': 'Depreciation - Office Equipment', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6170', 'name': 'Insurance - General', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},
    {'code': '6180', 'name': 'Taxes and Licenses', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '6100'},

    # Other Expenses
    {'code': '7000', 'name': 'Other Expenses', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': None},
    {'code': '7010', 'name': 'Interest Expense', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '7000'},
    {'code': '7020', 'name': 'Bank Charges', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '7000'},
    {'code': '7030', 'name': 'Miscellaneous Expense', 'type': 'Expense', 'classification': None, 'balance': 'Debit', 'parent': '7000'},
]

def create_coa():
    """Create the manufacturing chart of accounts"""
    with app.app_context():
        # Clear existing accounts
        print("Clearing existing accounts...")
        Account.query.delete()
        db.session.commit()
        print("[OK] Existing accounts cleared")

        # Create parent accounts first
        parent_accounts = {}

        # First pass: Create all accounts without parents
        print("\nCreating parent accounts...")
        for acc_data in manufacturing_coa:
            if acc_data['parent'] is None:
                account = Account(
                    code=acc_data['code'],
                    name=acc_data['name'],
                    account_type=acc_data['type'],
                    classification=acc_data['classification'],
                    normal_balance=acc_data['balance'],
                    parent_id=None
                )
                db.session.add(account)
                db.session.flush()  # Get the ID
                parent_accounts[acc_data['code']] = account.id
                print(f"  [OK] {acc_data['code']} - {acc_data['name']}")

        db.session.commit()

        # Second pass: Create child accounts
        print("\nCreating child accounts...")
        for acc_data in manufacturing_coa:
            if acc_data['parent'] is not None:
                parent_id = parent_accounts.get(acc_data['parent'])
                if parent_id:
                    # Get parent account to inherit properties
                    parent = Account.query.get(parent_id)

                    account = Account(
                        code=acc_data['code'],
                        name=acc_data['name'],
                        account_type=parent.account_type,  # Inherit from parent
                        classification=parent.classification,  # Inherit from parent
                        normal_balance=acc_data['balance'],  # Can differ from parent
                        parent_id=parent_id
                    )
                    db.session.add(account)
                    print(f"  [OK] {acc_data['code']} - {acc_data['name']} (child of {acc_data['parent']})")

        db.session.commit()

        # Summary
        total_accounts = Account.query.count()
        parent_count = Account.query.filter_by(parent_id=None).count()
        child_count = Account.query.filter(Account.parent_id.isnot(None)).count()

        print(f"\n{'='*60}")
        print(f"Chart of Accounts Created Successfully!")
        print(f"{'='*60}")
        print(f"Total Accounts: {total_accounts}")
        print(f"Parent Accounts: {parent_count}")
        print(f"Child Accounts: {child_count}")
        print(f"\nBreakdown by Account Type:")

        for acc_type in ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']:
            count = Account.query.filter_by(account_type=acc_type).count()
            print(f"  {acc_type}: {count} accounts")

if __name__ == '__main__':
    create_coa()
