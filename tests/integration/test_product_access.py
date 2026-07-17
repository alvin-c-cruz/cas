"""Tests for Product optional module registration (Task 9)."""
import pytest
from app.users.module_access import MODULE_REGISTRY, module_enabled, can_toggle, all_permission_keys

pytestmark = [pytest.mark.integration]


def test_products_registered_optional_depends_on_uom():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'products'), None)
    assert entry is not None
    assert entry['section'] == 'Maintenance' and entry['optional'] is True
    assert entry['default_enabled'] is False
    assert entry['depends_on'] == ['units_of_measure']
    assert entry['endpoints'] == ('products.',)
    assert entry.get('per_user') is True


def test_products_off_by_default(db_session):
    assert module_enabled('products') is False


def test_products_is_per_user_grantable():
    assert 'products' in all_permission_keys()


def test_cannot_enable_products_without_uom():
    # enabling products with UOM not in the enabled set is blocked
    ok, reason = can_toggle('products', enable=True, enabled_keys=set())
    assert ok is False and 'units_of_measure' in reason
    ok2, _ = can_toggle('products', enable=True, enabled_keys={'units_of_measure'})
    assert ok2 is True
