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
