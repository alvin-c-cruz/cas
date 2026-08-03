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

    # Receiving Report GRNI accrual (R-03 slice 2a-ii). Fully accountant-assigned --
    # deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES.
    # 'grni'               = Goods Received Not Invoiced -- the accrual liability RR
    #                        approval credits (net of VAT) and AP billing clears.
    # 'inventory_variance' = the plug when a bill's actual net amount differs from
    #                        what was accrued -- only resolved when that difference
    #                        is actually nonzero (conditional-resolve, same pattern
    #                        as petty_cash_short_over).
    'grni':                ('grni_account_code',                'Goods Received Not Invoiced (GRNI) control account'),
    'inventory_variance':  ('inventory_variance_account_code',  'Inventory Price/Quantity Variance control account'),

    # Delivery Receipt COGS relief (R-03 slice 2a-iii). Fully accountant-assigned --
    # deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES. No VAT, no variance -- COGS
    # is a pure cost figure, valued at whatever the product's current moving-average/
    # standard cost already is; nothing to reconcile against (unlike GRNI's accrual-
    # vs-actual-invoice gap).
    'cogs': ('cogs_account_code', 'Cost of Goods Sold control account'),

    # Manufacturing WIP (R-03 slice 2a-iv). Fully accountant-assigned --
    # deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES. Bridges
    # consume_materials (Dr wip/Cr inventory) and produce_finished_goods
    # (Dr inventory/Cr wip) -- shared by both the discrete (WorkOrder) and
    # process (ProductionRun, not yet built) manufacturing tracks.
    'wip': ('wip_account_code', 'Work-in-Process control account'),

    # Manufacturing labor (R-07 Discrete Track slice D4). Fully accountant-
    # assigned -- deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES. Credited
    # for the labor portion of a Work Order completion batch (labor is never
    # posted incrementally to WIP as operations complete -- see
    # app/work_orders/service.py's complete_work_order_batch).
    'labor_applied': ('labor_applied_account_code', 'Labor Applied control account'),

    # Abnormal spoilage (R-07 Process Track slice P6). Fully accountant-assigned --
    # deliberately NOT in DEFAULT_CONTROL_ACCOUNT_CODES: which expense account
    # abnormal loss lands in is a chart-of-accounts decision, and guessing one would
    # put a real charge somewhere nobody chose. Debited at close for
    # `abnormal loss units x cost per equivalent unit`, relieving WIP -- see
    # app/production_runs/costing.py for why only the ABNORMAL half is costed out
    # (normal loss is absorbed by the good units and never leaves WIP separately).
    'abnormal_loss': ('abnormal_loss_account_code', 'Abnormal Loss control account'),
}

# key -> owning optional module key, OR a tuple of keys when more than one module can post
# against it (shown if ANY of them is enabled). (app.users.module_access.MODULE_REGISTRY), used ONLY by the
# Company Settings > Control Accounts page to hide a field when its module is disabled (nothing
# can post against it anyway). A key absent from this dict is always shown -- ar_trade/ap_trade/
# creditable_wht/wht_payable are core/non-optional, never module-gated. Deliberately a SEPARATE
# dict rather than widening CONTROL_ACCOUNTS's own 2-tuple shape: that shape is unpacked in
# ~10 other test files plus app call sites, so changing it would ripple far wider than this
# display-only concern warrants (BUG-CONTROL-ACCOUNTS-NO-MODULE-GATING).
CONTROL_ACCOUNT_MODULE_GATE = {
    'payroll_salaries_expense':      'payroll',
    'payroll_sss_er_expense':        'payroll',
    'payroll_philhealth_er_expense': 'payroll',
    'payroll_pagibig_er_expense':    'payroll',
    'payroll_wht_payable':           'payroll',
    'payroll_sss_payable':           'payroll',
    'payroll_philhealth_payable':    'payroll',
    'payroll_pagibig_payable':       'payroll',
    'payroll_sss_loan_payable':      'payroll',
    'payroll_pagibig_loan_payable':  'payroll',
    'payroll_accrued_salaries':      'payroll',
    'inter_branch_due_from': 'bank_transfers',
    'inter_branch_due_to':   'bank_transfers',
    'gain_loss_on_disposal': 'fixed_asset_disposal',
    'petty_cash_short_over':         'petty_cash',
    'petty_cash_due_to_custodian':   'petty_cash',
    'inventory':                'inventory',
    'inventory_adjustment':     'inventory',
    'inventory_opening_equity': 'inventory',
    'grni':               'inventory',
    'inventory_variance': 'inventory',
    'cogs': 'inventory',
    'wip':  'bill_of_materials',
    # TWO owners since R-07 P4. D4 credits labor_applied for a Work Order's labor;
    # P4 credits it for a Production Run's applied conversion cost. A Philgen-shaped
    # install runs production_runs WITHOUT work_orders, and gating on work_orders
    # alone HID the field on exactly those installs -- while close still demanded the
    # account, which is a hard deadlock (the accountant is told to assign an account
    # whose field is not rendered). Found by the P4 browser gate, not by pytest:
    # every test sets control accounts directly and nothing renders the page.
    'labor_applied': ('work_orders', 'production_runs'),
    # ONE owner, deliberately -- not the two-track tuple above. Abnormal loss is a
    # period-costing concept: it needs an expected-loss percentage on the BOM and an
    # equivalent-units denominator to value the excess against, and the discrete track
    # has neither (D4's force-close writes its shortfall off to inventory_variance).
    # Naming work_orders here would render a field a discrete-only install can never
    # use -- the mirror image of the labor_applied bug, and just as much a defect.
    'abnormal_loss': 'production_runs',
}


def visible_control_accounts():
    """CONTROL_ACCOUNTS filtered to keys whose owning module (if any) is currently enabled.

    A gate value may be a single module key or a TUPLE of them; a tuple is satisfied
    when ANY of its modules is enabled, since any one of them can post against the
    account. See the labor_applied comment above for why that case exists.
    """
    from app.users.module_access import module_enabled

    def _visible(key):
        gate = CONTROL_ACCOUNT_MODULE_GATE.get(key)
        if gate is None:
            return True
        if isinstance(gate, str):
            return module_enabled(gate)
        return any(module_enabled(m) for m in gate)

    return {key: meta for key, meta in CONTROL_ACCOUNTS.items() if _visible(key)}

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
