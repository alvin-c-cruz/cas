"""Purchase Memo service helpers -- accountant-assigned target accounts.

Mirror of ``app/sales_memos/service.py`` for the buy side. The contra-expense
"Purchase Returns & Allowances" account and the "Vendor Credits" liability account
are NOT seeded per chart (they would collide with real charts) and are NOT
``app.posting.control_accounts`` entries -- verified by grepping the sales-side
equivalents (``sales_returns_allowances_account_code`` / ``customer_credits_
advances_account_code``): neither appears in ``CONTROL_ACCOUNTS``,
``DEFAULT_CONTROL_ACCOUNT_CODES``, any seed COA script, or any migration. The
accountant assigns them via a Purchase Memo settings page (to be added alongside
the module's views); they are stored as COA CODE strings in AppSettings and
resolved fail-closed at post time -- exactly like ``sales_memos.service.
resolve_memo_account`` / ``app/vat_settlement/service.py::resolve_target_account``.
"""
from app.accounts.models import Account
from app.settings import AppSettings

PURCHASE_RETURNS_KEY = 'purchase_returns_allowances_account_code'
VENDOR_CREDITS_KEY = 'vendor_credits_account_code'


def resolve_memo_account(setting_key, label):
    """Resolve an accountant-assigned target account. Fail-closed: NO default code."""
    code = AppSettings.get_setting(setting_key)   # None if unassigned
    if not code:
        raise ValueError(
            f'The {label} account is not assigned. Assign the Purchase Returns & Allowances '
            f'and Vendor Credits accounts on the Purchase Memo settings page before posting a memo.')
    acct = Account.query.filter_by(code=code).first()
    if acct is None:
        raise ValueError(
            f'The assigned {label} account (code {code}) is not in the Chart of Accounts. '
            f'Re-assign it on the Purchase Memo settings page before posting a memo.')
    return acct
