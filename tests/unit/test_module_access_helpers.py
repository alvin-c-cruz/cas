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
    for k in ('chart_of_accounts', 'general_ledger', 'ar_aging', 'ap_aging'):
        assert sec[k] == 'Ledger', f'{k} should be under Ledger'
    for k in ('customers', 'vendors'):
        assert sec[k] == 'Maintenance', f'{k} should be under Maintenance'
