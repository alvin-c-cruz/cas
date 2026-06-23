import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)


def test_bir_nav_present_when_enabled(client, db_session, admin_user, main_branch):
    # The module-enablement cache is session-scoped; clear it so a prior test that
    # disabled BIR cannot leak a stale value into this default-enabled assertion.
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    _login(client)
    resp = client.get('/dashboard')
    assert b'BIR Reports' in resp.data


def test_bir_nav_absent_when_disabled(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    resp = client.get('/dashboard')
    assert b'BIR Reports' not in resp.data
