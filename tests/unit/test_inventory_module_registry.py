import pytest

pytestmark = [pytest.mark.unit]


def test_inventory_module_registered_correctly():
    from app.users.module_access import MODULE_REGISTRY
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'inventory'), None)
    assert entry is not None
    assert entry['optional'] is True
    assert entry['depends_on'] == ['products']
    assert entry['default_enabled'] is False
    assert entry['per_user'] is True
    assert entry['endpoints'] == ()
    assert entry['section'] == 'Maintenance'


def test_inventory_requires_products_enabled_first():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('inventory', True, enabled_keys=set())
    assert ok is False and 'products' in reason
    ok2, _ = can_toggle('inventory', True, enabled_keys={'products'})
    assert ok2 is True


def test_inventory_in_per_user_permission_grid():
    from app.users.module_access import all_permission_keys
    assert 'inventory' in all_permission_keys()


def test_inventory_module_off_by_default(db_session):
    from app.users.module_access import module_enabled
    assert module_enabled('inventory') is False
