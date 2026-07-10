import pytest
from app.users.module_access import all_permission_keys, default_all_permissions, MODULE_REGISTRY

pytestmark = [pytest.mark.unit]


def test_all_permission_keys_excludes_optional_except_per_user():
    keys = all_permission_keys()
    # optional-and-NOT-per_user modules are excluded (instance-gated only)
    optional_not_per_user = [m['key'] for m in MODULE_REGISTRY
                             if m.get('optional') and not m.get('per_user')]
    assert 'accounts_payable' in keys
    assert 'bir_reports' not in keys           # optional, not per_user → excluded
    for k in optional_not_per_user:
        assert k not in keys
    # optional-BUT-per_user modules stay in the grid (e.g. sales_orders)
    assert 'sales_orders' in keys


def test_default_all_permissions_grants_every_non_optional_key():
    perms = default_all_permissions()
    assert set(perms.keys()) == set(all_permission_keys())
    assert all(v is True for v in perms.values())


def test_sections_align_with_sidebar():
    """MODULE_REGISTRY section grouping mirrors the sidebar: Ledger and Financial
    Reports are distinct groups (financial statements + year-end under Financial
    Reports), and master data under Maintenance."""
    sec = {m['key']: m['section'] for m in MODULE_REGISTRY}
    for k in ('income_statement', 'balance_sheet', 'cash_flow', 'trial_balance', 'fiscal_year_close'):
        assert sec[k] == 'Financial Reports', f'{k} should be under Financial Reports'
    for k in ('chart_of_accounts', 'general_ledger', 'ar_aging', 'ap_aging', 'books_of_accounts'):
        assert sec[k] == 'Ledger', f'{k} should be under Ledger'
    for k in ('customers', 'vendors'):
        assert sec[k] == 'Maintenance', f'{k} should be under Maintenance'


def _u(role, perms=None):
    from app.users.models import User
    u = User(username=f'{role}_vm', email=f'{role}_vm@t.com', full_name='VM', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    return u


def test_visible_modules_admin_sees_whole_section(db_session):
    from app.users.module_access import visible_modules
    keys = {m['key'] for m in visible_modules(_u('admin'), 'Ledger')}
    assert keys == {'chart_of_accounts', 'general_ledger', 'ar_aging', 'ap_aging',
                    'books_of_accounts', 'opening_balances', 'statement_of_account'}


def test_visible_modules_accountant_sees_only_granted(db_session):
    from app.users.module_access import visible_modules
    acct = _u('accountant', {'general_ledger': True})  # one Ledger module
    keys = {m['key'] for m in visible_modules(acct, 'Ledger')}
    assert keys == {'general_ledger'}


def test_visible_modules_empty_when_none_granted(db_session):
    from app.users.module_access import visible_modules
    acct = _u('accountant', {'accounts_receivable': True})  # no Ledger / FR modules
    assert visible_modules(acct, 'Ledger') == []
    assert visible_modules(acct, 'Financial Reports') == []


def test_visible_transactions_delegates_to_visible_modules(db_session):
    from app.users.module_access import visible_transactions, visible_modules
    acct = _u('accountant', {'accounts_receivable': True, 'collections': True})
    assert ({m['key'] for m in visible_transactions(acct)}
            == {m['key'] for m in visible_modules(acct, 'Transactions')}
            == {'accounts_receivable', 'collections'})
