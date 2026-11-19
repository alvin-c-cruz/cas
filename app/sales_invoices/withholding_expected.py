"""Per-branch switch: "Sales invoices in this branch should carry withholding tax" (WTX A, owner 14 Nov 2026; WTX-1 A,
17 Nov 2026; work order 2026-08-01-missing-default-wt-code-drops-cwt).

When it is on, a sales invoice warns -- never blocks -- when its customer has no withholding tax code. CAS has no
"corporate customer" field, and whether customers withhold is a fact about a client's branch (RIC CORP: every invoice
withholds; RIC EXTRA and Philgen: none), so the switch is per branch and lives in app_settings, not in code. Off by
default; set on the branch's edit page.
"""
from app.settings import AppSettings

SETTING_PREFIX = 'si_wt_expected'


def _key(branch_id):
    return f'{SETTING_PREFIX}:{branch_id}'


def wt_expected(branch_id):
    if not branch_id:
        return False
    return AppSettings.get_setting(_key(branch_id)) == '1'


def set_wt_expected(branch_id, on):
    AppSettings.set_setting(_key(branch_id), '1' if on else '0')


def customer_lacks_withholding(customer):
    return customer is not None and not list(customer.withholding_taxes)
