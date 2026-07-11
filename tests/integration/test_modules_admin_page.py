import pytest
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, pw):
    client.post('/login', data={'username': user, 'password': pw}, follow_redirects=True)


def test_page_admin_only(client, db_session, staff_user, main_branch):
    _login(client, staff_user.username, 'staff123')
    resp = client.get('/settings/modules', follow_redirects=True)
    assert b'Modules' not in resp.data or b'Only administrators' in resp.data


def test_settings_page_embeds_modules_table(client, db_session, admin_user, main_branch):
    """Packages tab: the modules toggle table is folded into /settings."""
    _login(client, 'admin', 'admin123')
    resp = client.get('/settings')
    assert resp.status_code == 200
    assert b'BIR Reports' in resp.data          # a known optional module label
    assert b'/settings/modules/toggle' in resp.data   # a per-row toggle form action


def test_modules_page_redirects_to_settings(client, db_session, admin_user, main_branch):
    """The standalone /modules page is retired -> redirects to the Packages tab."""
    _login(client, 'admin', 'admin123')
    resp = client.get('/settings/modules')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/settings')


def test_disable_persists_and_audits(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    _login(client, 'admin', 'admin123')
    client.post('/settings/modules/toggle',
                data={'key': 'bir_reports', 'enable': '0'}, follow_redirects=True)
    assert AppSettings.get_setting('module_enabled:bir_reports') == '0'
    log = AuditLog.query.filter_by(module='module_config', action='disable').first()
    assert log is not None and log.record_identifier == 'bir_reports'
