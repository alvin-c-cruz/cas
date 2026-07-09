"""Sales Memo service helpers -- accountant-assigned target accounts.

The contra-revenue "Sales Returns & Allowances" account and the "Customer Credits/
Advances" liability account are NOT seeded per chart (they collide with real charts).
The accountant assigns them via the Sales Memo settings page; they are stored as COA
CODE strings in AppSettings and resolved fail-closed at post time. Mirrors the VAT
settlement account-assignment pattern (app/vat_settlement/service.py::resolve_target_account).
"""
from app.accounts.models import Account
from app.settings import AppSettings

SALES_RETURNS_KEY = 'sales_returns_allowances_account_code'
CUSTOMER_CREDITS_KEY = 'customer_credits_advances_account_code'


def resolve_memo_account(setting_key, label):
    """Resolve an accountant-assigned target account. Fail-closed: NO default code."""
    code = AppSettings.get_setting(setting_key)   # None if unassigned
    if not code:
        raise ValueError(
            f'The {label} account is not assigned. Assign the Sales Returns & Allowances and '
            f'Customer Credits accounts on the Sales Memo settings page before posting a memo.')
    acct = Account.query.filter_by(code=code).first()
    if acct is None:
        raise ValueError(
            f'The assigned {label} account (code {code}) is not in the Chart of Accounts. '
            f'Re-assign it on the Sales Memo settings page before posting a memo.')
    return acct
