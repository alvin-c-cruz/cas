"""R-06 Payroll Government Remittance Reports (Task 2+): view/gating tests for
the two new endpoints per report (facsimile render + Excel export), registered
under the existing `payroll` module entry in app.users.module_access.
MODULE_REGISTRY -- no new toggle. PhilHealth/Pag-IBIG/BIR 1601-C (Tasks 3-5)
add their own test classes to this same file.
"""
import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

# tests/payroll/conftest.py's run_factory (and the payroll module autouse-enable
# fixture) live outside this directory's own conftest chain -- pull them in
# explicitly so this file can build a posted PayrollRun without redefining the
# factory. Mirrors how other cross-tree integration tests reuse a package's
# fixtures.
pytest_plugins = ['tests.payroll.conftest']

pytestmark = [pytest.mark.integration]


def _enable_payroll():
    AppSettings.set_setting('module_enabled:payroll', '1')
    clear_module_config_cache()


def _disable_payroll():
    AppSettings.set_setting('module_enabled:payroll', '0')
    clear_module_config_cache()


class TestSssRemittanceView:
    def test_view_renders_for_admin(self, client, db_session, login_user, admin_user,
                                     main_branch, run_factory):
        _enable_payroll()
        run = run_factory(run_number='PR-2026-06-0001')
        run.status = 'posted'
        db_session.commit()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = run.branch_id
        resp = client.get('/reports/payroll/sss-remittance?year=2026&month=6')
        assert resp.status_code == 200
        assert b'Juan Dela Cruz' in resp.data

    def test_export_excel_returns_workbook(self, client, db_session, login_user,
                                            admin_user, run_factory):
        _enable_payroll()
        run = run_factory(run_number='PR-2026-06-0001')
        run.status = 'posted'
        db_session.commit()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = run.branch_id
        resp = client.get('/reports/payroll/sss-remittance/export/excel?year=2026&month=6')
        assert resp.status_code == 200
        assert resp.content_type.startswith(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_route_blocked_when_payroll_disabled(self, client, db_session, login_user,
                                                   admin_user, main_branch):
        _disable_payroll()
        login_user(client, 'admin', 'admin123')
        # A branch must exist and be selected first, or the branch-session
        # before_request hook (which runs ahead of the module-access gate)
        # redirects to the branch picker before the module gate is ever
        # reached -- unrelated to what this test is actually checking.
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/reports/payroll/sss-remittance', follow_redirects=True)
        # Optional modules disabled at the instance level 404 for ALL roles,
        # including admin (see app/__init__.py::enforce_module_access) -- the
        # same convention proven by tests/payroll/test_module_gating.py's
        # TestModuleOffReturns404 class for the payroll module's own routes.
        assert (b'do not have access' in resp.data.lower()
                or resp.status_code in (302, 403, 404))
        _enable_payroll()  # restore for any test ordering that follows in this module


class TestPhilHealthRemittanceView:
    def test_view_renders_for_admin(self, client, db_session, login_user, admin_user,
                                     run_factory):
        _enable_payroll()
        run = run_factory(run_number='PR-2026-06-0002')
        run.status = 'posted'
        db_session.commit()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = run.branch_id
        resp = client.get('/reports/payroll/philhealth-remittance?year=2026&month=6')
        assert resp.status_code == 200
        assert b'Juan Dela Cruz' in resp.data

    def test_route_blocked_when_payroll_disabled(self, client, db_session, login_user,
                                                   admin_user, main_branch):
        _disable_payroll()
        login_user(client, 'admin', 'admin123')
        # A branch must exist and be selected first, or the branch-session
        # before_request hook (which runs ahead of the module-access gate)
        # redirects to the branch picker before the module gate is ever
        # reached -- same trap noted in TestSssRemittanceView above.
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/reports/payroll/philhealth-remittance', follow_redirects=True)
        # Optional modules disabled at the instance level 404 for ALL roles,
        # including admin (see app/__init__.py::enforce_module_access).
        assert (b'do not have access' in resp.data.lower()
                or resp.status_code in (302, 403, 404))
        _enable_payroll()
