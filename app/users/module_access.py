"""Per-user module access — enforce the existing `User.book_permissions` (staff-only).

The transaction "books" already existed as keys in `book_permissions`; this registry maps each
grantable module to its sidebar item and route endpoints so a single global `before_request`
hook and the sidebar template can gate them consistently.

Gating is STAFF-ONLY: admin, accountant, and viewer are never restricted here (matches the
branch-access model in `get_accessible_branches`). The `journals` blueprint is shared across
modules, so endpoints are matched per-prefix rather than per-blueprint.

`section` groups the checkboxes on the user-edit form and mirrors the sidebar sections.
"""

MODULE_REGISTRY = [
    # ── Transactions (Phase 1) ──────────────────────────────────────────────
    {'key': 'accounts_receivable', 'label': 'Sales Invoices', 'section': 'Transactions',
     'endpoints': ('sales_invoices.', 'journals.si_journal')},
    {'key': 'collections', 'label': 'Cash Receipts', 'section': 'Transactions',
     'endpoints': ('cash_receipts.', 'journals.cr_journal')},
    {'key': 'accounts_payable', 'label': 'Accounts Payable', 'section': 'Transactions',
     'endpoints': ('accounts_payable.', 'journals.ap_journal')},
    {'key': 'payments', 'label': 'Cash Disbursements', 'section': 'Transactions',
     'endpoints': ('cash_disbursements.', 'journals.cd_journal')},
    {'key': 'journal_entries', 'label': 'Journal Voucher', 'section': 'Transactions',
     'endpoints': ('journal_entries.', 'journals.voucher')},
    # ── Master data + ledger (Phase 2; deny-by-default for staff) ────────────
    {'key': 'customers', 'label': 'Customers', 'section': 'Maintenance',
     'endpoints': ('customers.',)},
    {'key': 'vendors', 'label': 'Vendors', 'section': 'Maintenance',
     'endpoints': ('vendors.',)},
    {'key': 'chart_of_accounts', 'label': 'Chart of Accounts', 'section': 'Ledger',
     'endpoints': ('accounts.',)},
    {'key': 'ap_aging', 'label': 'Aging of AP', 'section': 'Ledger',
     'endpoints': ('reports.ap_aging', 'reports.ap_aging_export_excel', 'reports.ap_aging_export_csv')},
    {'key': 'ar_aging', 'label': 'Aging of AR', 'section': 'Ledger',
     'endpoints': ('reports.ar_aging', 'reports.ar_aging_export_excel', 'reports.ar_aging_export_csv')},
    {'key': 'general_ledger', 'label': 'General Ledger', 'section': 'Ledger',
     'endpoints': ('reports.general_ledger', 'reports.general_ledger_export_excel',
                   'reports.general_ledger_export_csv', 'reports.general_ledger_print')},
    {'key': 'trial_balance', 'label': 'Trial Balance', 'section': 'Ledger',
     'endpoints': ('reports.trial_balance', 'reports.trial_balance_export_excel',
                   'reports.trial_balance_export_csv', 'reports.trial_balance_print')},
]

TRANSACTION_KEYS = [m['key'] for m in MODULE_REGISTRY if m['section'] == 'Transactions']

# Vendor sub-actions reached FROM transaction forms (inline quick-add + autofill). These must
# stay reachable for a staff user who has a transaction module but not the Vendors module —
# otherwise the AP/CD quick-add and the AP vendor-defaults autofill would break.
EXEMPT_ENDPOINTS = {'vendors.create', 'vendors.vendor_defaults'}


def module_key_for_endpoint(endpoint):
    """Return the book key that guards a Flask endpoint, or None if unguarded/exempt."""
    if not endpoint or endpoint in EXEMPT_ENDPOINTS:
        return None
    for m in MODULE_REGISTRY:
        for pref in m['endpoints']:
            if endpoint == pref or endpoint.startswith(pref):
                return m['key']
    return None


def can_access_module(user, key):
    """Staff-only gating: admin/accountant/viewer always True; staff checked against their
    book_permissions; anonymous False."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.role in ('admin', 'accountant', 'viewer'):
        return True
    return user.get_book_permissions().get(key, False)


def visible_transactions(user):
    """Transaction registry entries the user may see — used to hide the whole Transactions
    section when a staff user has been granted none of them."""
    return [m for m in MODULE_REGISTRY
            if m['section'] == 'Transactions' and can_access_module(user, m['key'])]
