"""Task 15: payroll module gating.

Registers `payroll` in MODULE_REGISTRY (optional, per_user, depends_on
['employees'], area='Payroll'). The single `payroll_bp` blueprint
(app/payroll/__init__.py) means every payroll view's endpoint is named
'payroll.<view>', so ONE 'payroll.' prefix entry in the registry's
`endpoints` tuple gates every payroll route -- past and future -- via
module_key_for_endpoint's `endpoint.startswith(pref)` match. This is
verified directly below by exercising every route class named in the task
brief (worksheet new/edit incl. 13th-month, register, detail, post/void/
cancel, loan list/create/edit/delete) rather than assuming the theory holds.

tests/payroll/conftest.py's `_payroll_module_enabled` autouse fixture turns
the package ON by default (module_enabled:payroll=1) so the rest of the
payroll suite (test_lifecycle.py, test_loans_13th.py, ...) keeps working
unmodified now that payroll is gated. The OFF-state tests here explicitly
flip it back to '0' after that autouse setup runs.
"""
from decimal import Decimal

import pytest

from app.employees.models import Employee
from app.payroll.models import EmployeeLoan
from app.settings import AppSettings
from app.users.module_access import MODULE_REGISTRY, build_sidebar, can_access_module
from app.users.models import User
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _disable_payroll():
    AppSettings.set_setting('module_enabled:payroll', '0')
    clear_module_config_cache()


def _enable_payroll():
    AppSettings.set_setting('module_enabled:payroll', '1')
    clear_module_config_cache()


def _login_staff(client, login_user, staff_user, main_branch, db_session):
    staff_user.branches.append(main_branch)
    db_session.commit()
    login_user(client, 'staff', 'staff123')


class TestRegistryEntry:
    def test_payroll_registered_correctly(self):
        entry = next(m for m in MODULE_REGISTRY if m['key'] == 'payroll')
        assert entry['label'] == 'Payroll'
        assert entry['area'] == 'Payroll'
        assert entry.get('optional') is True
        assert entry.get('per_user') is True
        assert entry.get('depends_on') == ['employees']
        assert entry.get('default_enabled') is False
        # Task 2 (SSS remittance) onward: individual report endpoints ride
        # alongside the 'payroll.' prefix rather than replacing it -- each
        # report route lives in the reports blueprint, so it needs its own
        # exact-match string here (module_key_for_endpoint has no prefix to
        # match on 'reports.').
        assert entry['endpoints'] == (
            'payroll.', 'reports.sss_remittance', 'reports.sss_remittance_export_excel')

    def test_every_actual_payroll_endpoint_is_matched_by_the_registry_prefix(self, app):
        """Enumerate every route Flask actually registered under the payroll
        blueprint and prove each one's endpoint name is caught by the single
        'payroll.' prefix -- the single-blueprint theory, checked, not assumed."""
        payroll_endpoints = [r.endpoint for r in app.url_map.iter_rules()
                              if r.endpoint.startswith('payroll.')]
        # Sanity: the blueprint really does have multiple distinct view functions.
        assert len(set(payroll_endpoints)) >= 11
        from app.users.module_access import module_key_for_endpoint
        for ep in payroll_endpoints:
            assert module_key_for_endpoint(ep) == 'payroll', \
                f"endpoint {ep} not gated by the payroll module"


class TestModuleOffReturns404:
    """Every payroll route class 404s (not a redirect, not a rendered page)
    when the instance package is disabled -- for ALL roles, including admin
    (module_enabled gate runs before the per-user book_permissions check)."""

    @pytest.fixture(autouse=True)
    def _off(self, db_session):
        _disable_payroll()
        yield

    def test_register_404(self, client, staff_user, main_branch, login_user, db_session):
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/runs').status_code == 404

    def test_worksheet_new_404(self, client, staff_user, main_branch, login_user, db_session):
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/runs/new').status_code == 404
        assert client.post('/payroll/runs/new', data={}).status_code == 404

    def test_worksheet_13th_month_new_404(self, client, staff_user, main_branch, login_user, db_session):
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/runs/new?run_type=13th_month&year=2026').status_code == 404

    def test_worksheet_edit_404(self, client, staff_user, main_branch, login_user, db_session, run_factory):
        # Use a REAL run id -- a nonexistent id would 404 on its own (resource-not-found),
        # which would pass even without module gating and prove nothing about the gate.
        run = run_factory()
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get(f'/payroll/runs/{run.id}/edit').status_code == 404
        assert client.post(f'/payroll/runs/{run.id}/edit', data={}).status_code == 404

    def test_detail_404(self, client, staff_user, main_branch, login_user, db_session, run_factory):
        run = run_factory()
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get(f'/payroll/runs/{run.id}').status_code == 404

    def test_post_void_cancel_404(self, client, accountant_user, main_branch, login_user, db_session,
                                   run_factory):
        # ONE real draft run reused for all 3 actions -- the module gate must intercept
        # BEFORE any status check/mutation runs, so status never actually flips here
        # (each POST 404s at the before_request hook, not inside the view).
        # accountant_user fixture already assigns main_branch.
        run = run_factory()
        login_user(client, 'accountant', 'accountant123')
        assert client.post(f'/payroll/runs/{run.id}/post', data={}).status_code == 404
        assert client.post(f'/payroll/runs/{run.id}/void', data={}).status_code == 404
        assert client.post(f'/payroll/runs/{run.id}/cancel', data={}).status_code == 404

    def test_loan_list_create_edit_delete_404(self, client, staff_user, main_branch, login_user, db_session):
        emp = Employee(employee_no='EMP-GATE-OFF', first_name='Rico', last_name='Santos',
                        branch_id=main_branch.id, pay_basis='monthly', basic_rate=Decimal('20000.00'),
                        pay_frequency='monthly', tax_status_code='S')
        db_session.add(emp)
        db_session.flush()
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000.00'),
                             monthly_amortization=Decimal('500.00'), balance=Decimal('6000.00'),
                             status='active')
        db_session.add(loan)
        db_session.commit()
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/loans').status_code == 404
        assert client.get('/payroll/loans/new').status_code == 404
        assert client.post('/payroll/loans/new', data={}).status_code == 404
        assert client.get(f'/payroll/loans/{loan.id}/edit').status_code == 404
        assert client.post(f'/payroll/loans/{loan.id}/edit', data={}).status_code == 404
        assert client.post(f'/payroll/loans/{loan.id}/delete', data={}).status_code == 404

    def test_404_even_for_admin(self, client, admin_user, main_branch, login_user, db_session):
        login_user(client, 'admin', 'admin123')
        assert client.get('/payroll/runs').status_code == 404
        assert client.get('/payroll/loans').status_code == 404


class TestModuleOnWorksNormally:
    """With the package enabled (and the user's own book_permissions
    granting 'payroll', per staff_user's fixture), each route class renders
    normally. Detailed business-logic correctness is already proven by
    test_lifecycle.py / test_loans_13th.py -- this only re-confirms gating
    doesn't interfere with the ON path."""

    def test_register_and_worksheet_new_200(self, client, staff_user, main_branch, login_user, db_session):
        _enable_payroll()
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/runs').status_code == 200
        assert client.get('/payroll/runs/new').status_code == 200
        assert client.get('/payroll/runs/new?run_type=13th_month&year=2026').status_code == 200

    def test_loans_list_and_new_200(self, client, staff_user, main_branch, login_user, db_session):
        _enable_payroll()
        _login_staff(client, login_user, staff_user, main_branch, db_session)
        assert client.get('/payroll/loans').status_code == 200
        assert client.get('/payroll/loans/new').status_code == 200

    def test_detail_edit_and_loan_edit_200(self, client, staff_user, main_branch, login_user,
                                            db_session, run_factory):
        _enable_payroll()
        run = run_factory()
        emp = Employee(employee_no='EMP-GATE-1', first_name='Rico', last_name='Santos',
                        branch_id=main_branch.id, pay_basis='monthly', basic_rate=Decimal('25000.00'),
                        pay_frequency='monthly', tax_status_code='S')
        db_session.add(emp)
        loan = EmployeeLoan(employee_id=run.lines[0].employee_id, loan_type='sss',
                             principal=Decimal('6000.00'), monthly_amortization=Decimal('500.00'),
                             balance=Decimal('6000.00'), status='active')
        db_session.add(loan)
        _login_staff(client, login_user, staff_user, main_branch, db_session)

        assert client.get(f'/payroll/runs/{run.id}').status_code == 200
        assert client.get(f'/payroll/runs/{run.id}/edit').status_code == 200
        assert client.get(f'/payroll/loans/{loan.id}/edit').status_code == 200


class TestPerUserGating:
    """payroll is per_user=True: the package can be ON for the instance while
    an individual user still lacks the book_permissions grant -- distinct
    from the package-off 404, this is a redirect-with-flash (can_access_module
    returns False on the per-user check, not the instance-package check)."""

    def test_enabled_package_but_ungranted_user_is_redirected_not_404(
            self, client, main_branch, login_user, db_session):
        _enable_payroll()
        user = User(username='nopay', email='nopay@test.com', full_name='No Payroll',
                    role='staff', is_active=True)
        user.set_password('nopay123')
        user.set_book_permissions({})   # explicitly withheld
        db_session.add(user)
        db_session.flush()
        user.branches.append(main_branch)
        db_session.commit()

        login_user(client, 'nopay', 'nopay123')
        resp = client.get('/payroll/runs', follow_redirects=True)
        assert resp.status_code == 200   # redirected to dashboard, not 404
        assert b'do not have access' in resp.data


class TestSidebarGating:
    def test_payroll_hidden_from_sidebar_when_package_off(self, db_session, admin_user):
        _disable_payroll()
        tree = build_sidebar(admin_user)
        areas = [a['area'] for a in tree]
        assert 'Payroll' not in areas

    def test_payroll_shown_in_sidebar_when_package_on(self, db_session, admin_user):
        _enable_payroll()
        try:
            tree = build_sidebar(admin_user)
            payroll_area = next((a for a in tree if a['area'] == 'Payroll'), None)
            assert payroll_area is not None, f"'Payroll' area missing; got {[a['area'] for a in tree]}"
            all_keys = [m['key'] for g in payroll_area['groups'] for m in g['modules']]
            assert 'payroll' in all_keys
        finally:
            clear_module_config_cache()

    def test_can_access_module_false_when_off_true_when_on_for_admin(self, db_session, admin_user):
        _disable_payroll()
        assert can_access_module(admin_user, 'payroll') is False
        _enable_payroll()
        try:
            assert can_access_module(admin_user, 'payroll') is True
        finally:
            clear_module_config_cache()
