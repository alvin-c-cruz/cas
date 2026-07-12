"""Resolve posting control (GL) accounts from accountant-assigned settings.

Replaces the historical hardcoded ``Account.query.filter_by(code='10201')``
lookups scattered across the posting engines (BUG-POSTING-HARDCODED-CONTROL-
ACCOUNTS). Per the no-hardcoded-master-data-refs rule, engines resolve control
accounts ONLY through this module; the legacy codes survive solely as
seed/migration/test defaults in ``DEFAULT_CONTROL_ACCOUNT_CODES``.
"""
from app.accounts.models import Account
from app.settings import AppSettings

# control key -> (AppSettings key, human label)
CONTROL_ACCOUNTS = {
    'ar_trade':       ('ar_trade_account_code',       'Accounts Receivable control account'),
    'ap_trade':       ('ap_trade_account_code',       'Accounts Payable control account'),
    'creditable_wht': ('creditable_wht_account_code', 'Creditable Withholding Tax control account'),
    'wht_payable':    ('wht_payable_account_code',    'Withholding Tax Payable control account'),
}

# Legacy magic codes -> control key. Used ONLY by seeds, the backfill migration,
# and test setup -- NEVER by get_control_account. Single place the legacy chart's
# control codes are named.
DEFAULT_CONTROL_ACCOUNT_CODES = {
    'ar_trade':       '10201',
    'ap_trade':       '20101',
    'creditable_wht': '10212',
    'wht_payable':    '20301',
}


class ControlAccountError(ValueError):
    """Unassigned/misassigned control account. Subclasses ValueError so the
    posting views' existing ``except ValueError`` / ``except Exception`` handlers
    surface the message as a flash instead of a 500."""


def get_control_account(key, required=True):
    """Resolve the Account assigned to control-account ``key``.

    required=True  -> raise ControlAccountError (friendly) when unassigned or the
                      assigned code has no matching account.
    required=False -> return None instead of raising (preview / report paths).
    """
    setting_key, label = CONTROL_ACCOUNTS[key]
    code = (AppSettings.get_setting(setting_key) or '').strip()
    if not code:
        if required:
            raise ControlAccountError(
                f"Assign the {label} in Company Settings → Control Accounts "
                f"before posting.")
        return None
    account = Account.query.filter_by(code=code).first()
    if account is None:
        if required:
            raise ControlAccountError(
                f"The {label} is set to code {code}, which is not in the chart of "
                f"accounts. Update it in Company Settings → Control Accounts.")
        return None
    return account


def assign_default_control_accounts(updated_by='system'):
    """Best-effort: assign each control-account setting from its legacy default
    code IF an account with that code exists and the setting is unassigned. Used
    by seeds; the backfill migration does the equivalent for existing prod DBs."""
    for key, code in DEFAULT_CONTROL_ACCOUNT_CODES.items():
        setting_key, _ = CONTROL_ACCOUNTS[key]
        if AppSettings.get_setting(setting_key):
            continue
        if Account.query.filter_by(code=code).first() is not None:
            AppSettings.set_setting(setting_key, code, updated_by=updated_by)


def get_postable_accounts():
    """Active leaf (postable) accounts, ordered by code. A node is a group
    header if it is top-level (no parent_id) OR has children; otherwise it is
    a leaf (matches the derived-hierarchy rule used across CAS)."""
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in accounts if a.parent_id is not None}
    return [a for a in accounts
            if a.parent_id is not None and a.id not in parent_ids]
