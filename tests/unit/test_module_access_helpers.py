import pytest
from app.users.module_access import all_permission_keys, default_all_permissions, MODULE_REGISTRY

pytestmark = [pytest.mark.unit]


def test_all_permission_keys_excludes_optional():
    keys = all_permission_keys()
    optional = [m['key'] for m in MODULE_REGISTRY if m.get('optional')]
    assert 'accounts_payable' in keys
    assert 'bir_reports' not in keys           # optional → excluded
    for k in optional:
        assert k not in keys


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
                    'books_of_accounts', 'opening_balances'}


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


# ---------------------------------------------------------------------------
# Pre-Printed Voucher Forms registry entries (P-69 Task 6) — deliberately
# endpoint-less/non-rendering shape. See app/preprinted_forms/views.py module
# docstring and app/users/module_access.py for the rationale.
# ---------------------------------------------------------------------------

def test_preprinted_forms_registry_entry_is_optional_default_off_endpointless():
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'preprinted_forms')
    assert entry.get('optional') is True
    assert entry.get('default_enabled') is False
    assert entry['endpoints'] == ()
    assert entry['area'] is None
    assert entry['group'] is None


def test_print_layouts_registry_entry_is_core_endpointless():
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'print_layouts')
    assert 'optional' not in entry
    assert entry['endpoints'] == ()
    assert entry['area'] is None
    assert entry['group'] is None
    assert 'print_layouts' in all_permission_keys()


def test_preprinted_forms_module_disabled_by_default(db_session):
    from app.users.module_access import module_enabled
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    try:
        assert module_enabled('preprinted_forms') is False
    finally:
        clear_module_config_cache()


def test_preprinted_forms_and_print_layouts_never_appear_in_sidebar(db_session):
    """Both keys have area=None/group=None (outside AREA_ORDER/GROUP_ORDER), so
    build_sidebar must never surface them for any role, even a full-access admin
    with the module instance-enabled."""
    from app.users.module_access import build_sidebar
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    from app import db as _db

    AppSettings.set_setting('module_enabled:preprinted_forms', '1')
    _db.session.commit()
    clear_module_config_cache()
    try:
        admin = _u('admin')
        tree = build_sidebar(admin)
        keys = {m['key'] for area in tree for g in area['groups'] for m in g['modules']}
        assert 'preprinted_forms' not in keys
        assert 'print_layouts' not in keys
    finally:
        clear_module_config_cache()
