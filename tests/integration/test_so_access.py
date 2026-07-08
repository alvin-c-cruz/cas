"""Registry + permission-key assertions for the sales_orders module."""
import pytest
from app.users.module_access import MODULE_REGISTRY, all_permission_keys

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def test_sales_orders_registered_optional_products_gated():
    e = next((m for m in MODULE_REGISTRY if m['key'] == 'sales_orders'), None)
    assert e is not None, "sales_orders not in MODULE_REGISTRY"
    assert e['section'] == 'Transactions'
    assert e['area'] == 'Sales'
    # Optional, Products-gated, but per-user grantable — so still in the permission grid
    assert e.get('optional') is True, "sales_orders is now an optional module"
    assert e.get('per_user') is True and e.get('default_enabled') is False
    assert e.get('depends_on') == ['products']
    assert 'sales_orders' in all_permission_keys()   # per_user keeps it out of admin-only
    assert e['endpoints'] == ('sales_orders.',)
