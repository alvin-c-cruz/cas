from app.users.module_access import module_enabled, MODULE_REGISTRY, all_permission_keys


def test_employees_registered_optional_default_off(app):
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'employees'), None)
    assert entry is not None
    assert entry['optional'] is True
    assert entry.get('default_enabled') is False
    assert entry['area'] == 'Payroll'
    assert entry.get('per_user') is True


def test_employees_disabled_by_default(db_session):
    # module_enabled reads app_settings, so tables must exist (db_session fixture).
    assert module_enabled('employees') is False


def test_employees_is_per_user_grantable():
    assert 'employees' in all_permission_keys()
