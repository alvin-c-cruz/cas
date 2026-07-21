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

    # Payroll v1 (R-06) control accounts. Fully accountant-assigned -- deliberately
    # NOT added to DEFAULT_CONTROL_ACCOUNT_CODES below, so no seed script or
    # migration ever auto-assigns them (mirrors app/vat_settlement/service.py's
    # resolve_target_account: "Fail-closed: NO default code"). An accountant must
    # assign each one in Company Settings -> Control Accounts before payroll can post.
    'payroll_salaries_expense':      ('payroll_salaries_expense_account_code',      'Salaries Expense control account'),
    'payroll_sss_er_expense':        ('payroll_sss_er_expense_account_code',        'SSS Employer Share Expense control account'),
    'payroll_philhealth_er_expense': ('payroll_philhealth_er_expense_account_code', 'PhilHealth Employer Share Expense control account'),
    'payroll_pagibig_er_expense':    ('payroll_pagibig_er_expense_account_code',    'Pag-IBIG Employer Share Expense control account'),
    'payroll_wht_payable':           ('payroll_wht_payable_account_code',           'Withholding Tax on Compensation Payable control account'),
    'payroll_sss_payable':           ('payroll_sss_payable_account_code',           'SSS Contributions Payable control account'),
    'payroll_philhealth_payable':    ('payroll_philhealth_payable_account_code',    'PhilHealth Contributions Payable control account'),
    'payroll_pagibig_payable':       ('payroll_pagibig_payable_account_code',       'Pag-IBIG Contributions Payable control account'),
    'payroll_sss_loan_payable':      ('payroll_sss_loan_payable_account_code',      'SSS Salary/Calamity Loan Payable control account'),
    'payroll_pagibig_loan_payable':  ('payroll_pagibig_loan_payable_account_code',  'Pag-IBIG Loan Payable control account'),
    'payroll_accrued_salaries':      ('payroll_accrued_salaries_account_code',      'Accrued Salaries and Wages control account'),

    # Bank Transfers (R-04 slice 2). Fully accountant-assigned -- deliberately NOT
    # added to DEFAULT_CONTROL_ACCOUNT_CODES, so no seed/migration auto-assigns them
    # from a guessed code (illustrative codes like 10215/20110 collide with existing
    # seed rows on some charts). An accountant must assign both before any
    # INTER-BRANCH transfer can post; intra-branch transfers never touch these.
    'inter_branch_due_from': ('inter_branch_due_from_account_code', 'Inter-branch Due-from control account'),
    'inter_branch_due_to':   ('inter_branch_due_to_account_code',   'Inter-branch Due-to control account'),

    # Fixed Asset Disposal (R-05 Slice 3). Fully accountant-assigned -- deliberately NOT
    # added to DEFAULT_CONTROL_ACCOUNT_CODES, so no seed/migration auto-assigns it. An
    # accountant must assign it in Company Settings -> Control Accounts before any
    # disposal can post.
    'gain_loss_on_disposal': ('gain_loss_on_disposal_account_code',
                              'Gain/Loss on Disposal of Fixed Assets control account'),

    # Petty Cash (R-04 slice 4). Fail-closed, no default code (same reasoning as
    # the inter-branch clearing pair) -- but only ever RESOLVED when a nonzero
    # shortage/overage actually exists on a given replenishment; an exact-tie
    # replenishment must post fine while this stays unassigned.
    'petty_cash_short_over': ('petty_cash_short_over_account_code', 'Cash Short/Over control account'),
    # The liability leg of every replenishment JE (owner decision: accrual-then-
    # manual-pay, mirroring Payroll v1's Accrued Salaries pattern -- see
    # app/petty_cash/replenishment.py's module docstring). Fail-closed, no
    # default code -- ALWAYS resolved (not conditional like the short/over key
    # above), since every replenishment credits this account regardless of
    # whether there's a shortage/overage.
    'petty_cash_due_to_custodian': ('petty_cash_due_to_custodian_account_code', 'Due to Petty Cash Custodian control account'),

    # Inventory / Stock Ledger (R-03 slice 2a-i). Fully accountant-assigned --
    # deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES, so no seed/migration
    # auto-assigns them (same reasoning as the petty-cash and disposal keys).
    # 'inventory'                = the Inventory asset control account (every stock movement's asset leg)
    # 'inventory_adjustment'     = P&L offset for a genuine correction (found/lost/write-off) -- a gain or loss
    # 'inventory_opening_equity' = equity offset for an opening-stock load at cutover (never the P&L)
    'inventory':                ('inventory_account_code',                'Inventory control account'),
    'inventory_adjustment':     ('inventory_adjustment_account_code',     'Inventory Adjustment (gain/loss) control account'),
    'inventory_opening_equity': ('inventory_opening_equity_account_code', 'Inventory Opening Balance Equity control account'),
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
