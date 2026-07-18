"""R-06 Payroll Government Remittance Reports (Task 2+): view/gating tests for
the two new endpoints per report (facsimile render + Excel export), registered
under the existing `payroll` module entry in app.users.module_access.
MODULE_REGISTRY -- no new toggle. PhilHealth/Pag-IBIG/BIR 1601-C (Tasks 3-5)
add their own test classes to this same file.

Lives under tests/payroll/ (not tests/integration/) specifically so it picks up
tests/payroll/conftest.py's run_factory and the payroll module autouse-enable
fixture via ordinary directory-scoped conftest resolution -- no `pytest_plugins`
needed. An earlier version of this file lived in tests/integration/ and reached
those fixtures via `pytest_plugins = ['tests.payroll.conftest']`, which silently
promotes ALL of that conftest's fixtures (including its autouse module-enable/
cache-clear fixture) to apply to the ENTIRE pytest session, not just this file --
confirmed to leak into and break unrelated tests/integration/test_vat_settlement_views.py
tests (a stale-cache dependency in those tests got exposed by our fixture's
extra clear_module_config_cache() calls running before/after every single test
in tests/integration/). Moved here 2026-07-18 during the pre-merge test-suite
verification pass; see the finishing-a-development-branch SDD ledger.
"""
import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

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


class TestPagibigRemittanceView:
    def test_view_renders_for_admin(self, client, db_session, login_user, admin_user,
                                     run_factory):
        _enable_payroll()
        run = run_factory(run_number='PR-2026-06-0003')
        run.status = 'posted'
        db_session.commit()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = run.branch_id
        resp = client.get('/reports/payroll/pagibig-remittance?year=2026&month=6')
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
        resp = client.get('/reports/payroll/pagibig-remittance', follow_redirects=True)
        assert (b'do not have access' in resp.data.lower()
                or resp.status_code in (302, 403, 404))
        _enable_payroll()


class TestBir1601cView:
    def test_view_renders_for_admin(self, client, db_session, login_user, admin_user,
                                     run_factory):
        _enable_payroll()
        run = run_factory(run_number='PR-2026-06-0004')
        run.status = 'posted'
        db_session.commit()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = run.branch_id
        resp = client.get('/reports/payroll/bir-1601c?year=2026&month=6')
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
        resp = client.get('/reports/payroll/bir-1601c', follow_redirects=True)
        assert (b'do not have access' in resp.data.lower()
                or resp.status_code in (302, 403, 404))
        _enable_payroll()


class TestRemittanceHub:
    def test_hub_renders_with_links_to_all_four_reports(self, client, db_session,
                                                          login_user, admin_user, main_branch):
        _enable_payroll()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/reports/payroll')
        assert resp.status_code == 200
        assert b'SSS' in resp.data
        assert b'PhilHealth' in resp.data
        assert b'Pag-IBIG' in resp.data
        assert b'1601-C' in resp.data

    def test_payroll_register_page_links_to_hub(self, client, db_session, login_user,
                                                  admin_user, main_branch):
        _enable_payroll()
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/payroll/runs')
        assert resp.status_code == 200
        assert b'/reports/payroll' in resp.data
