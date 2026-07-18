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
    # ── Transactions (Phase 1) ─────────────────────────────────────────────
    # ── Sales Area (optional — per-company configurable) ───────────────────
    # Ordered along the Order-to-Cash chain (Quotation -> SO -> DR -> SI -> CR),
    # memos last as post-sale adjustments. build_sidebar preserves this order within
    # the Sales/Documents group (owner request 2026-07-11: Quotations first).
    {'key': 'quotations', 'label': 'Quotations', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['sales_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('quotations.',)},
    # job_order_slips MUST be registered before sales_orders below: module_key_for_endpoint()
    # matches the FIRST entry whose endpoint prefix fits, and sales_orders' own prefix
    # ('sales_orders.') would otherwise swallow these two routes first. Own grantable
    # permission -- an operations user can hold this without holding full sales_orders access.
    {'key': 'job_order_slips', 'label': 'Job Order Slips', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['sales_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('sales_orders.job_order_', 'sales_orders.print_job_order')},
    {'key': 'sales_orders', 'label': 'Sales Orders', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['products'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('sales_orders.',)},
    {'key': 'delivery_receipts', 'label': 'Delivery Receipts', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['sales_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('delivery_receipts.',)},
    {'key': 'accounts_receivable', 'label': 'Sales Invoices', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'endpoints': ('sales_invoices.', 'journals.si_journal')},
    {'key': 'collections', 'label': 'Cash Receipts', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'endpoints': ('cash_receipts.', 'journals.cr_journal')},
    {'key': 'credit_memos', 'label': 'Credit Memos', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('sales_memos.credit_',)},
    {'key': 'debit_memos', 'label': 'Debit Notes', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('sales_memos.debit_',)},
    # ── Purchases Area (optional — per-company configurable) ───────────────
    # Ordered along the Procure-to-Pay chain (PR -> PO -> RR -> Bill -> Pay).
    {'key': 'purchase_requests', 'label': 'Purchase Requests', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'optional': True, 'depends_on': ['purchase_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('purchase_requests.',)},
    {'key': 'purchase_orders', 'label': 'Purchase Orders', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'optional': True, 'depends_on': ['products'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('purchase_orders.',)},
    {'key': 'receiving_reports', 'label': 'Receiving Reports', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'optional': True, 'depends_on': ['purchase_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('receiving_reports.',)},
    {'key': 'accounts_payable', 'label': 'Accounts Payable', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'endpoints': ('accounts_payable.', 'journals.ap_journal')},
    {'key': 'payments', 'label': 'Cash Disbursements', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'endpoints': ('cash_disbursements.', 'journals.cd_journal')},
    {'key': 'vendor_debit_memos', 'label': 'Vendor Debit Memos', 'section': 'Transactions',
     'area': 'Purchases', 'group': 'Documents',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('purchase_memos.debit_', 'purchase_memos.settings',
                   'purchase_memos.save_accounts')},
    {'key': 'journal_entries', 'label': 'Journal Voucher', 'section': 'Transactions',
     'area': 'Accounting', 'group': 'Journals',
     'endpoints': ('journal_entries.', 'journals.voucher')},
    # ── Payroll Area (optional — per-company configurable) ──────────────────
    # Single blueprint (app/payroll/__init__.py: Blueprint('payroll', ...)) covers every
    # payroll route (worksheet new/edit incl. 13th-month, register, detail/JE-preview,
    # post/void/cancel, loan list/create/edit/delete) — every payroll endpoint is named
    # 'payroll.<view>', so the one 'payroll.' prefix gates all of them, past and future
    # (see module_key_for_endpoint's endpoint.startswith(pref) match below).
    {'key': 'payroll', 'label': 'Payroll', 'section': 'Transactions',
     'area': 'Payroll', 'group': 'Documents',
     'optional': True, 'depends_on': ['employees'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('payroll.', 'reports.payroll_remittances_index',
                   'reports.sss_remittance', 'reports.sss_remittance_export_excel',
                   'reports.philhealth_remittance', 'reports.philhealth_remittance_export_excel',
                   'reports.pagibig_remittance', 'reports.pagibig_remittance_export_excel',
                   'reports.bir_1601c', 'reports.bir_1601c_export_excel')},
    # ── Ledger (Phase 2; deny-by-default for staff) — mirrors the sidebar's
    #    "Ledger" section, in the same order ──────────────────────────────────
    {'key': 'opening_balances', 'label': 'Opening Balances', 'section': 'Ledger',
     'area': 'Accounting', 'group': 'Journals',
     'endpoints': ('opening_balances.',)},
    {'key': 'chart_of_accounts', 'label': 'Chart of Accounts', 'section': 'Ledger',
     'area': 'Accounting', 'group': 'Ledger',
     'endpoints': ('accounts.',)},
    {'key': 'general_ledger', 'label': 'General Ledger', 'section': 'Ledger',
     'area': 'Accounting', 'group': 'Ledger',
     'endpoints': ('reports.general_ledger', 'reports.general_ledger_export_excel',
                   'reports.general_ledger_export_csv', 'reports.general_ledger_print')},
    {'key': 'books_of_accounts', 'label': 'Books of Accounts', 'section': 'Ledger',
     'area': 'Compliance', 'group': 'BIR',
     'endpoints': ('reports.books_of_accounts', 'reports.books_print_all',
                   'reports.books_export_all', 'reports.general_journal',
                   'reports.general_journal_print', 'reports.general_journal_export')},
    {'key': 'ar_aging', 'label': 'Aging of AR', 'section': 'Ledger',
     'area': 'Sales', 'group': 'Reports',
     'endpoints': ('reports.ar_aging', 'reports.ar_aging_export_excel', 'reports.ar_aging_export_csv')},
    {'key': 'statement_of_account', 'label': 'Statement of Account', 'section': 'Ledger',
     'area': 'Sales', 'group': 'Reports',
     'endpoints': ('reports.statement_of_account', 'reports.statement_of_account_print',
                   'reports.statement_of_account_export_excel')},
    {'key': 'ap_aging', 'label': 'Aging of AP', 'section': 'Ledger',
     'area': 'Purchases', 'group': 'Reports',
     'endpoints': ('reports.ap_aging', 'reports.ap_aging_export_excel', 'reports.ap_aging_export_csv')},
    # ── Financial Reports — mirrors the sidebar's "Financial Reports" section ─
    {'key': 'income_statement', 'label': 'Income Statement', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('reports.income_statement', 'reports.income_statement_export_excel',
                   'reports.income_statement_print')},
    {'key': 'balance_sheet', 'label': 'Balance Sheet', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('reports.balance_sheet', 'reports.balance_sheet_export_excel',
                   'reports.balance_sheet_print')},
    {'key': 'cash_flow', 'label': 'Cash Flow', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('reports.cash_flow', 'reports.cash_flow_export_excel',
                   'reports.cash_flow_print')},
    {'key': 'trial_balance', 'label': 'Trial Balance', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('reports.trial_balance', 'reports.trial_balance_export_excel',
                   'reports.trial_balance_print')},
    {'key': 'periods', 'label': 'Accounting Periods', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('periods.',)},
    {'key': 'fiscal_year_close', 'label': 'Year-End Close', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'endpoints': ('year_end.index', 'year_end.close', 'year_end.reopen')},
    {'key': 'sales_by_product_line', 'label': 'Sales by Product Line', 'section': 'Financial Reports',
     # depends on BOTH products and the product_categories master: without categories
     # every sales line reports as 'Unassigned', so the report is meaningless (retro #148).
     'area': 'Accounting', 'group': 'Financial Statements',
     'optional': True, 'depends_on': ['products', 'product_categories'], 'default_enabled': False,
     'endpoints': ('reports.sales_by_product_line', 'reports.sales_by_product_line_print',
                   'reports.sales_by_product_line_export_excel')},
    {'key': 'budgeting', 'label': 'Budget Entry', 'section': 'Financial Reports',
     'area': 'Accounting', 'group': 'Financial Statements',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('budgeting.',)},
    # ── Maintenance (master data; deny-by-default for staff) ─────────────────
    {'key': 'customers', 'label': 'Customers', 'section': 'Maintenance',
     'area': 'Sales', 'group': 'Masters',
     'endpoints': ('customers.',)},
    {'key': 'vendors', 'label': 'Vendors', 'section': 'Maintenance',
     'area': 'Purchases', 'group': 'Masters',
     'endpoints': ('vendors.',)},
    {'key': 'units_of_measure', 'label': 'Units of Measure', 'section': 'Maintenance',
     'area': 'Inventory', 'group': 'Masters',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('units_of_measure.',)},
    {'key': 'product_categories', 'label': 'Product Categories', 'section': 'Maintenance',
     'area': 'Inventory', 'group': 'Masters',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('product_categories.',)},
    {'key': 'products', 'label': 'Products', 'section': 'Maintenance',
     'area': 'Inventory', 'group': 'Masters',
     'optional': True, 'depends_on': ['units_of_measure'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('products.',)},
    {'key': 'employees', 'label': 'Employees', 'section': 'Maintenance',
     'area': 'Payroll', 'group': 'Masters',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('employees.',)},
    {'key': 'fixed_assets', 'label': 'Fixed Assets', 'section': 'Maintenance',
     'area': 'Fixed Assets', 'group': 'Masters',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('fixed_assets.',)},
    {'key': 'fixed_asset_depreciation', 'label': 'Depreciation', 'section': 'Transactions',
     'area': 'Fixed Assets', 'group': 'Documents',
     'optional': True, 'depends_on': ['fixed_assets'], 'default_enabled': False,
     'endpoints': ('fixed_asset_depreciation.',)},
    {'key': 'fixed_asset_disposal', 'label': 'Disposal', 'section': 'Transactions',
     'area': 'Fixed Assets', 'group': 'Documents',
     'optional': True, 'depends_on': ['fixed_assets', 'fixed_asset_depreciation'],
     'default_enabled': False, 'endpoints': ('fixed_asset_disposal.',)},
    # ── Reports (optional / configurable module) ─────────────────────────────
    {'key': 'bir_reports', 'label': 'BIR Reports', 'section': 'Reports',
     'area': 'Compliance', 'group': 'BIR',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('reports.bir_index', 'reports.bir_sales', 'reports.bir_sales_export_excel',
                   'reports.bir_purchases', 'reports.bir_purchases_export_excel',
                   'reports.bir_alphalist', 'reports.bir_alphalist_export_excel',
                   'reports.bir_2307_index', 'reports.bir_2307_print',
                   'reports.bir_vat_return', 'reports.bir_vat_return_export_excel',
                   'reports.bir_vat_return_print',
                   'withholding_certificates.',
                   'vat_settlement.')},
    # ── Banking (R-04 slice 1) — Cash & Bank register over existing COA accounts ──
    # NOTE: per_user=True (deliberate deviation from the plan's literal snippet, which
    # had per_user=False). With per_user=False this optional module is excluded from
    # all_permission_keys()/default_all_permissions() -- a plain 'accountant' (not
    # has_full_access) could then NEVER be granted it, same structural trap as
    # bir_reports (admin/CA-only in practice). The task's own given test creates a
    # bank account as accountant_user right after enabling the module at the instance
    # level, which requires per_user=True so accountant_user's default_all_permissions()
    # fixture grant includes this key -- matching the staff/accountant-reachable
    # optional Transaction modules (sales_orders, purchase_requests, etc.), not the
    # admin-only reports.
    {'key': 'bank_accounts', 'label': 'Bank Accounts', 'section': 'Transactions',
     'area': 'Banking', 'group': 'Banking',
     'optional': True, 'depends_on': [], 'default_enabled': False, 'per_user': True,
     'endpoints': ('bank_accounts.',)},
    # ── Bank Transfers (R-04 slice 2) — lifecycle over Bank Accounts ──────────
    # NOTE: per_user=True (deliberate deviation from the task brief's literal snippet,
    # which had per_user=False -- same trap as bank_accounts above: with per_user=False
    # this optional module is excluded from all_permission_keys()/default_all_permissions(),
    # so a plain 'accountant'/'staff' (not has_full_access) could NEVER be granted it,
    # no matter what an admin does on the user-permission grid). per_user=True keeps it
    # both instance-gated (module_enabled) and individually grantable, matching
    # bank_accounts and the other staff/accountant-reachable optional Transaction modules.
    {'key': 'bank_transfers', 'label': 'Bank Transfers', 'section': 'Transactions',
     'area': 'Banking', 'group': 'Banking',
     'optional': True, 'depends_on': ['bank_accounts'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('bank_transfers.',)},
    # ── Petty Cash Fund (R-04 slice 4) — same per_user=True precedent as bank_transfers ──
    {'key': 'petty_cash', 'label': 'Petty Cash', 'section': 'Transactions',
     'area': 'Banking', 'group': 'Banking',
     'optional': True, 'depends_on': ['bank_accounts'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('petty_cash.',)},
    # ── Bank Reconciliation (R-04 slice 3) — same per_user=True precedent as its
    # Banking-area siblings; accountant+-only (no staff tier at all, unlike
    # petty_cash's two-tier split) via the module's own inline role check.
    {'key': 'bank_reconciliation', 'label': 'Bank Reconciliation', 'section': 'Transactions',
     'area': 'Banking', 'group': 'Banking',
     'optional': True, 'depends_on': ['bank_accounts'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('bank_reconciliation.',)},
]

AREA_ORDER = ['Sales', 'Purchases', 'Inventory', 'Banking', 'Accounting', 'Compliance', 'Payroll',
              'Fixed Assets', 'Admin']
GROUP_ORDER = ['Documents', 'Masters', 'Journals', 'Ledger', 'Financial Statements', 'Reports', 'BIR', 'Admin',
               'Banking']

TRANSACTION_KEYS = [m['key'] for m in MODULE_REGISTRY
                    if m['section'] == 'Transactions' and not m.get('optional')]

# Vendor/customer sub-actions reached FROM transaction forms (inline quick-add + autofill).
# These must stay reachable for a staff user who has a transaction module but not the
# Vendors/Customers master-data module — otherwise the AP/CD vendor quick-add + defaults, and
# the Quotation/SI/SO customer quick-add + defaults, would break (the module guard would
# redirect the XHR to the dashboard and leave the line-items grid locked).
EXEMPT_ENDPOINTS = {'vendors.create', 'vendors.vendor_defaults', 'employees.create',
                    'customers.create', 'customers.customer_defaults',
                    'products.create'}


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
    if user.has_full_access:
        return True
    return user.get_book_permissions().get(key, False)


# Billing-support endpoints: these two JSON endpoints exist solely to feed the Accounts
# Payable billing picker (AP's own create form calls them to list billable POs/RRs for a
# vendor) -- they are not general views of the purchase_orders/receiving_reports modules.
# A staff user scoped only to 'accounts_payable' (the intended least-privilege AP role) must
# still reach them even without PO/RR module access. Additive: a user who already has the
# endpoint's own module access still passes via the normal can_access_module() check in
# enforce_module_access -- this is only a second, alternate path in, never a narrowing.
BILLING_SUPPORT_ENDPOINTS = {
    'purchase_orders.billable_pos': 'accounts_payable',
    'receiving_reports.billable_rrs': 'accounts_payable',
}


def can_access_billing_support_endpoint(user, endpoint):
    """True if *user* may reach a billing-support endpoint via its AP-scoped exception."""
    alt_key = BILLING_SUPPORT_ENDPOINTS.get(endpoint)
    return alt_key is not None and can_access_module(user, alt_key)


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
    path and the form grid. EXCEPTION: an optional module flagged per_user (e.g.
    sales_orders) is both instance-gated AND per-user grantable, so it stays in
    the grid — a bare optional would silently drop it to admin-only."""
    return [m['key'] for m in MODULE_REGISTRY if not m.get('optional') or m.get('per_user')]


def default_all_permissions():
    """Grant dict for every non-optional module. Used by the migration backfill,
    seeds, and test fixtures so newly-gated accountants/viewers keep full access
    until deliberately narrowed."""
    return {k: True for k in all_permission_keys()}


def build_sidebar(user):
    """Nested visible Area -> group -> module tree for the sidebar.
    Visibility reuses can_access_module (no gating reimplemented)."""
    visible = [m for m in MODULE_REGISTRY if can_access_module(user, m['key'])]
    tree = []
    for area in AREA_ORDER:
        area_mods = [m for m in visible if m.get('area') == area]
        if not area_mods:
            continue
        groups = []
        for group in GROUP_ORDER:
            group_mods = [m for m in area_mods if m.get('group') == group]
            if group_mods:
                groups.append({'group': group, 'modules': group_mods})
        if groups:
            tree.append({'area': area, 'groups': groups})
    return tree
