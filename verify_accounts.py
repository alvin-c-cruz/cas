"""Verify critical accounts were loaded correctly."""
from app import create_app
from app.accounts.models import Account

app = create_app()

with app.app_context():
    accounts = Account.query.order_by(Account.code).all()

    print('\n' + '='*80)
    print('CRITICAL ACCOUNTS LOADED')
    print('='*80)
    print(f'{"Code":<8} | {"Account Name":<45} | {"Type":<10} | {"Balance"}')
    print('-'*80)

    for acc in accounts:
        print(f'{acc.code:<8} | {acc.name:<45} | {acc.account_type:<10} | {acc.normal_balance}')

    print('='*80)
    print(f'Total: {len(accounts)} accounts')
    print()

    # Summary by account type
    print('SUMMARY BY ACCOUNT TYPE:')
    print('-'*40)
    for acc_type in ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']:
        count = Account.query.filter_by(account_type=acc_type).count()
        print(f'  {acc_type:<15}: {count:2} accounts')
    print()

    # Critical BIR accounts verification
    print('BIR COMPLIANCE ACCOUNTS:')
    print('-'*40)
    bir_accounts = [
        '1200',  # Input Tax
        '1210',  # Creditable Withholding Tax
        '2100',  # Output VAT Payable
        '2110',  # Withholding Tax Payable - Expanded
        '2120',  # Withholding Tax Payable - Compensation
        '2200',  # SSS Payable
        '2210',  # PhilHealth Payable
        '2220',  # Pag-IBIG Payable
    ]

    for code in bir_accounts:
        acc = Account.query.filter_by(code=code).first()
        if acc:
            print(f'  [OK] {acc.code} - {acc.name}')
        else:
            print(f'  [MISSING] {code}')

    print()
