import pytest
from app.employees.models import Employee


@pytest.fixture
def employees_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    from app import db
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_quick_add_employee_returns_json(client, admin_user, branch_manila, login_user,
                                         employees_module_enabled):
    login_user(client, 'admin', 'admin123')
    resp = client.post('/employees/create',
                       data={'employee_no': 'EMP-0001', 'first_name': 'Alvin', 'last_name': 'Cruz',
                             'branch_id': str(branch_manila.id), 'is_active': '1',
                             'qualified_dependents': '0', 'user_id': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['employee']['label'].startswith('EMP-0001')
    assert Employee.query.count() == 1
