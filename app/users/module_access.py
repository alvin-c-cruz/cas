"""Per-user module access — enforce the existing `User.book_permissions` (staff-only).

The 5 transaction "books" already exist as keys in `book_permissions`
(`accounts_receivable`, `collections`, `accounts_payable`, `payments`, `journal_entries`).
This registry maps each to its sidebar item and route endpoints so a single global
`before_request` hook and the sidebar template can gate them consistently.

Gating is STAFF-ONLY: admin, accountant, and viewer are never restricted here (matches the
branch-access model in `get_accessible_branches`). The `journals` blueprint is shared across
modules, so endpoints are matched per-prefix rather than per-blueprint.
"""

MODULE_REGISTRY = [
    {'key': 'accounts_receivable', 'label': 'Sales Invoices',
     'endpoints': ('sales_invoices.', 'journals.si_journal')},
    {'key': 'collections', 'label': 'Cash Receipts',
     'endpoints': ('receipts.',)},
    {'key': 'accounts_payable', 'label': 'Accounts Payable',
     'endpoints': ('accounts_payable.', 'journals.ap_journal')},
    {'key': 'payments', 'label': 'Cash Disbursements',
     'endpoints': ('cash_disbursements.', 'journals.cd_journal')},
    {'key': 'journal_entries', 'label': 'Journal Voucher',
     'endpoints': ('journal_entries.', 'journals.voucher')},
]

TRANSACTION_KEYS = [m['key'] for m in MODULE_REGISTRY]


def module_key_for_endpoint(endpoint):
    """Return the book key that guards a Flask endpoint, or None if unguarded."""
    if not endpoint:
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
    """Registry entries the user may see — used to hide the whole Transactions section
    when a staff user has been granted none of them."""
    return [m for m in MODULE_REGISTRY if can_access_module(user, m['key'])]
