"""Registry + permission-key assertions for the sales_orders module."""
import pytest
from app.users.module_access import MODULE_REGISTRY, all_permission_keys

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def test_sales_orders_registered_core_sales_area():
    e = next((m for m in MODULE_REGISTRY if m['key'] == 'sales_orders'), None)
    assert e is not None, "sales_orders not in MODULE_REGISTRY"
    assert e['section'] == 'Transactions'
    assert e['area'] == 'Sales'
    # CORE module (non-optional, per P-58) — appears in per-user permission grid
    assert not e.get('optional'), "sales_orders must be non-optional (CORE)"
    assert 'sales_orders' in all_permission_keys()
    assert e['endpoints'] == ('sales_orders.',)
