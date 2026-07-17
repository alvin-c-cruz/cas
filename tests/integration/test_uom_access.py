from app.users.module_access import MODULE_REGISTRY, module_enabled, all_permission_keys


def test_units_of_measure_registered_optional_maintenance():
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'units_of_measure'), None)
    assert entry is not None
    assert entry['section'] == 'Maintenance'
    assert entry['optional'] is True
    assert entry['default_enabled'] is False
    assert entry['endpoints'] == ('units_of_measure.',)
    assert entry.get('per_user') is True


def test_units_of_measure_off_by_default(db_session):
    # optional + default_enabled False → module_enabled False until an admin turns it on
    assert module_enabled('units_of_measure') is False


def test_units_of_measure_is_per_user_grantable():
    # optional-and-per_user modules ARE part of the per-user permission grid
    assert 'units_of_measure' in all_permission_keys()
