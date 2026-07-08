import pytest

pytestmark = [pytest.mark.integration]


def test_bir_defaults_enabled(db_session):
    from app.users.module_access import module_enabled
    assert module_enabled('bir_reports') is True   # default_enabled=True, no setting


def test_core_module_always_enabled(db_session):
    from app.users.module_access import module_enabled
    assert module_enabled('accounts_payable') is True   # not optional → always on


def test_disabling_bir_hides_it_for_admin(db_session, admin_user):
    from app.settings import AppSettings
    from app.users.module_access import can_access_module, module_enabled
    from app.utils.cache_helpers import clear_module_config_cache

    assert can_access_module(admin_user, 'bir_reports') is True
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    assert module_enabled('bir_reports') is False
    assert can_access_module(admin_user, 'bir_reports') is False   # disabled → off for ALL roles
    assert can_access_module(admin_user, 'accounts_payable') is True   # core unaffected


def test_new_optional_module_defaults_off(db_session, monkeypatch):
    from app.users import module_access
    monkeypatch.setattr(module_access, 'MODULE_REGISTRY', module_access.MODULE_REGISTRY + [
        {'key': 'demo_optional', 'label': 'Demo', 'section': 'Reports',
         'optional': True, 'depends_on': [], 'default_enabled': False, 'endpoints': ()}
    ])
    assert module_access.module_enabled('demo_optional') is False


def test_sales_orders_requires_products_to_enable():
    from app.users.module_access import can_toggle
    ok, reason = can_toggle('sales_orders', True, enabled_keys=[])
    assert ok is False and 'products' in reason
    ok2, _ = can_toggle('sales_orders', True, enabled_keys=['units_of_measure', 'products'])
    assert ok2 is True


def test_sales_orders_stays_in_per_user_grid_though_optional():
    from app.users.module_access import all_permission_keys, MODULE_REGISTRY
    entry = next(m for m in MODULE_REGISTRY if m['key'] == 'sales_orders')
    assert entry['optional'] is True and entry.get('per_user') is True
    assert 'sales_orders' in all_permission_keys()   # not dropped to admin-only


def test_sales_orders_disabled_by_default(db_session):
    from app.users.module_access import module_enabled
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    assert module_enabled('sales_orders') is False   # default_enabled False, no override
