"""Render-assertion: the payslip print settings fields exist on the Company
Settings form and page, gated behind the payroll module (mirrors the existing
TestPayrollSemiMonthlyTimingSetting pattern in test_company_settings_views.py)."""
import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def payroll_module_enabled(db_session):
    """Enables the payroll module for the test, then clears the shared
    module-config cache again at teardown -- the cache lives on the
    session-scoped `app` fixture, so leaving a stale '1' cached here would
    leak into any later test in the same run that doesn't explicitly clear
    it (found live: this leak was silently defeating
    tests/unit/test_sidebar_nav.py::test_admin_sees_all_areas_ordered under
    full-suite ordering)."""
    AppSettings.set_setting('module_enabled:payroll', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_payslip_settings_fields_render_when_payroll_enabled(
        client, db_session, admin_user, main_branch, payroll_module_enabled):
    login(client)

    resp = client.get('/settings')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'payslip_print_form' in html
    assert 'payslip_print_access' in html


def test_payslip_settings_fields_absent_when_payroll_disabled(
        client, db_session, admin_user, main_branch):
    # module_enabled:payroll intentionally left unset (default disabled).
    # Explicitly clear the module-config cache: it lives on the session-scoped
    # `app` fixture, so a prior test in this file enabling the module would
    # otherwise leak a stale '1' into this test's (function-scoped) fresh DB.
    clear_module_config_cache()
    login(client)

    resp = client.get('/settings')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'payslip_print_form' not in html
