"""Registry + permission-key assertions for the sales_orders module."""
import pytest
from app.users.module_access import MODULE_REGISTRY, all_permission_keys

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def test_sales_orders_registered_core_transactions():
    e = next((m for m in MODULE_REGISTRY if m['key'] == 'sales_orders'), None)
    assert e is not None, "sales_orders not in MODULE_REGISTRY"
    assert e['section'] == 'Transactions'
    # CORE module — must NOT have optional flag (or explicit False)
    assert 'optional' not in e or e.get('optional') is False
    # Core → in all_permission_keys (per-user grantable)
    assert 'sales_orders' in all_permission_keys()
    assert e['endpoints'] == ('sales_orders.',)
