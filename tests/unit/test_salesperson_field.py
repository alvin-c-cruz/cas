import pytest
from datetime import date
from app import db
from app.employees.models import Employee
from app.sales_orders.models import SalesOrder, copy_salesperson

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _emp(db_session, branch_id):
    e = Employee(employee_no='E-001', first_name='Jane', last_name='Cruz',
                 branch_id=branch_id, is_active=True)
    db_session.add(e); db_session.commit()
    return e


def test_so_salesperson_fk_and_to_dict(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    so = SalesOrder(so_number='SO-SP-1', order_date=date(2026, 7, 8), customer_id=1,
                    customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    db_session.add(so); db_session.commit()
    assert so.salesperson.full_name == 'Jane Cruz'
    d = so.to_dict()
    assert d['salesperson_id'] == e.id and d['salesperson_name'] == 'Jane Cruz'
    so2 = SalesOrder(so_number='SO-SP-2', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    db_session.add(so2); db_session.commit()
    assert so2.to_dict()['salesperson_name'] is None


def test_copy_salesperson(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    src = SalesOrder(so_number='SO-SP-3', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    dst = SalesOrder(so_number='SO-SP-4', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    copy_salesperson(src, dst)
    assert dst.salesperson_id == e.id


def test_salesperson_choices_only_includes_flagged_employees(app, db_session, main_branch, request):
    from app.sales_orders.views import _salesperson_choices
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    db_session.commit(); clear_module_config_cache()
    # Clear again at teardown -- the module-config cache lives on the
    # session-scoped `app` fixture, so leaving a stale '1' here leaks into any
    # later test in the same run that doesn't explicitly clear it (found
    # live: this leak was silently defeating
    # tests/unit/test_sidebar_nav.py::test_admin_sees_all_areas_ordered under
    # full-suite ordering, via the 'Payroll' area which employees also gates).
    request.addfinalizer(clear_module_config_cache)
    db_session.add(Employee(employee_no='S1', first_name='Sal', last_name='Rep',
                            branch_id=main_branch.id, is_active=True, is_salesperson=True))
    db_session.add(Employee(employee_no='A1', first_name='Ac', last_name='Count',
                            branch_id=main_branch.id, is_active=True, is_salesperson=False))
    db_session.commit()
    with app.test_request_context():
        labels = [lbl for (val, lbl) in _salesperson_choices(main_branch.id)]
    assert any('S1' in l for l in labels)       # salesperson included
    assert not any('A1' in l for l in labels)   # non-salesperson excluded
