import pytest

pytestmark = [pytest.mark.unit]

CATALOG = [
    {'key': 'a', 'optional': True, 'depends_on': []},
    {'key': 'b', 'optional': True, 'depends_on': ['a']},
]


def test_enable_blocked_when_prereq_off():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('b', True, enabled_keys=set(), registry=CATALOG)
    assert ok is False and 'a' in reason


def test_enable_allowed_when_prereq_on():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('b', True, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True


def test_disable_blocked_when_dependent_enabled():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('a', False, enabled_keys={'a', 'b'}, registry=CATALOG)
    assert ok is False and 'b' in reason


def test_disable_allowed_when_no_dependent():
    from app.users.module_access import can_toggle
    ok, _ = can_toggle('a', False, enabled_keys={'a'}, registry=CATALOG)
    assert ok is True


def test_sales_by_product_line_requires_products_and_categories():
    """The report groups sales by product->category; enabling it without the
    product_categories master would make every line 'Unassigned'. So it must
    depend on BOTH products and product_categories (real MODULE_REGISTRY)."""
    from app.users.module_access import MODULE_REGISTRY, can_toggle
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'sales_by_product_line')
    assert set(entry['depends_on']) == {'products', 'product_categories'}
    # products on but category master off -> refused (would be all-Unassigned)
    ok, reason = can_toggle('sales_by_product_line', True, enabled_keys={'products'})
    assert ok is False and 'product_categories' in reason
    # both prerequisites on -> allowed
    ok2, _ = can_toggle('sales_by_product_line', True,
                        enabled_keys={'products', 'product_categories'})
    assert ok2 is True
