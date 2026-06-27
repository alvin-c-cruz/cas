"""Per-user module access — enforce the existing `User.book_permissions` for all non-admin roles.

The transaction "books" already existed as keys in `book_permissions`; this registry maps each
grantable module to its sidebar item and route endpoints so a single global `before_request`
hook and the sidebar template can gate them consistently.

Gating applies to ALL roles except admin: accountant, staff, and viewer are all subject to
`book_permissions`. Admin is always granted.  The `journals` blueprint is shared across
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
    # ── Ledger (Phase 2; deny-by-default for staff) — mirrors the sidebar's
    #    "Ledger" section, in the same order ──────────────────────────────────
    {'key': 'chart_of_accounts', 'label': 'Chart of Accounts', 'section': 'Ledger',
     'endpoints': ('accounts.',)},
    {'key': 'general_ledger', 'label': 'General Ledger', 'section': 'Ledger',
     'endpoints': ('reports.general_ledger', 'reports.general_ledger_export_excel',
                   'reports.general_ledger_export_csv', 'reports.general_ledger_print')},
    {'key': 'ar_aging', 'label': 'Aging of AR', 'section': 'Ledger',
     'endpoints': ('reports.ar_aging', 'reports.ar_aging_export_excel', 'reports.ar_aging_export_csv')},
    {'key': 'ap_aging', 'label': 'Aging of AP', 'section': 'Ledger',
     'endpoints': ('reports.ap_aging', 'reports.ap_aging_export_excel', 'reports.ap_aging_export_csv')},
    # ── Financial Reports — mirrors the sidebar's "Financial Reports" section ─
    {'key': 'income_statement', 'label': 'Income Statement', 'section': 'Financial Reports',
     'endpoints': ('reports.income_statement', 'reports.income_statement_export_excel',
                   'reports.income_statement_print')},
    {'key': 'balance_sheet', 'label': 'Balance Sheet', 'section': 'Financial Reports',
     'endpoints': ('reports.balance_sheet', 'reports.balance_sheet_export_excel',
                   'reports.balance_sheet_print')},
    {'key': 'cash_flow', 'label': 'Cash Flow', 'section': 'Financial Reports',
     'endpoints': ('reports.cash_flow', 'reports.cash_flow_export_excel',
                   'reports.cash_flow_print')},
    {'key': 'trial_balance', 'label': 'Trial Balance', 'section': 'Financial Reports',
     'endpoints': ('reports.trial_balance', 'reports.trial_balance_export_excel',
                   'reports.trial_balance_print')},
    {'key': 'fiscal_year_close', 'label': 'Year-End Close', 'section': 'Financial Reports',
     'endpoints': ('year_end.index', 'year_end.close', 'year_end.reopen')},
    # ── Maintenance (master data; deny-by-default for staff) ─────────────────
    {'key': 'customers', 'label': 'Customers', 'section': 'Maintenance',
     'endpoints': ('customers.',)},
    {'key': 'vendors', 'label': 'Vendors', 'section': 'Maintenance',
     'endpoints': ('vendors.',)},
    {'key': 'units_of_measure', 'label': 'Units of Measure', 'section': 'Maintenance',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('units_of_measure.',)},
    # ── Reports (optional / configurable module) ─────────────────────────────
    {'key': 'bir_reports', 'label': 'BIR Reports', 'section': 'Reports',
     'optional': True, 'depends_on': [], 'default_enabled': True,
     'endpoints': ('reports.bir_index', 'reports.bir_sales', 'reports.bir_sales_export_excel',
                   'reports.bir_purchases', 'reports.bir_purchases_export_excel',
                   'reports.bir_alphalist', 'reports.bir_alphalist_export_excel')},
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


def module_enabled(key):
    """Instance-level package gate: is this optional module included? Core/unknown → True."""
    entry = next((m for m in MODULE_REGISTRY if m['key'] == key), None)
    if not entry or not entry.get('optional'):
        return True
    from app.utils.cache_helpers import get_module_override
    raw = get_module_override(key)
    return entry.get('default_enabled', False) if raw is None else (raw == '1')


def can_access_module(user, key):
    """Instance package gate (all roles; disabled optional module → False), then anonymous → False,
    then per-user gate (admin always True; accountant/staff/viewer by book_permissions)."""
    if not module_enabled(key):
        return False
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.role == 'admin':
        return True
    return user.get_book_permissions().get(key, False)


def can_toggle(key, enable, enabled_keys, registry=MODULE_REGISTRY):
    """Validate a module toggle against dependencies. Returns (ok, reason)."""
    entry = next((m for m in registry if m['key'] == key), None)
    if entry is None:
        return (False, 'unknown module')
    if enable:
        missing = [d for d in entry.get('depends_on', []) if d not in enabled_keys]
        return (not missing, f"requires {', '.join(missing)}" if missing else '')
    dependents = [m['key'] for m in registry
                  if m.get('optional') and key in m.get('depends_on', []) and m['key'] in enabled_keys]
    return (not dependents, f"in use by {', '.join(dependents)}" if dependents else '')


def visible_modules(user, section):
    """Registry entries in `section` the user may access — used to hide a whole sidebar
    section when the user has none of its modules. Mirrors the per-item gate so section
    visibility and item visibility never disagree."""
    return [m for m in MODULE_REGISTRY
            if m['section'] == section and can_access_module(user, m['key'])]


def visible_transactions(user):
    """Transaction entries the user may see (kept for existing callers)."""
    return visible_modules(user, 'Transactions')


def all_permission_keys():
    """Non-optional module keys that make up the per-user permission grid.

    Optional modules (e.g. bir_reports) are instance-gated via module_enabled,
    never per-user, so they are excluded here — matching the admin user-save
    path and the form grid."""
    return [m['key'] for m in MODULE_REGISTRY if not m.get('optional')]


def default_all_permissions():
    """Grant dict for every non-optional module. Used by the migration backfill,
    seeds, and test fixtures so newly-gated accountants/viewers keep full access
    until deliberately narrowed."""
    return {k: True for k in all_permission_keys()}
