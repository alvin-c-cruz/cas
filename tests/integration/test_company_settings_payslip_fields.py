"""Render-assertion: the payslip print settings fields exist on the Company
Settings form and page, gated behind the payroll module (mirrors the existing
TestPayrollSemiMonthlyTimingSetting pattern in test_company_settings_views.py)."""
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _enable_payroll_module(db_session):
    AppSettings.set_setting('module_enabled:payroll', '1')
    db_session.commit()
    clear_module_config_cache()


def test_payslip_settings_fields_render_when_payroll_enabled(
        client, db_session, admin_user, main_branch):
    _enable_payroll_module(db_session)
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
