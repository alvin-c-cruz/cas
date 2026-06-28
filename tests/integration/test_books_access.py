"""Integration test: books_of_accounts MODULE_REGISTRY entry shape (Task 9)."""
from app.users.module_access import MODULE_REGISTRY


def test_books_of_accounts_registered_in_ledger_section():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'books_of_accounts'), None)
    assert entry is not None
    assert entry['section'] == 'Ledger'
    assert 'reports.books_of_accounts' in entry['endpoints']
    assert 'reports.general_journal' in entry['endpoints']


def test_books_of_accounts_is_core_not_optional():
    """books_of_accounts must be a core module (no optional flag) so it is always enabled
    and appears in the per-user permission grid via all_permission_keys()."""
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'books_of_accounts'), None)
    assert entry is not None
    assert not entry.get('optional', False)


def test_books_of_accounts_endpoints_complete():
    """All six books endpoints must be listed so the before_request gate covers them."""
    expected = {
        'reports.books_of_accounts',
        'reports.books_print_all',
        'reports.books_export_all',
        'reports.general_journal',
        'reports.general_journal_print',
        'reports.general_journal_export',
    }
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'books_of_accounts'), None)
    assert entry is not None
    assert expected.issubset(set(entry['endpoints']))
