import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)


def test_bir_nav_present_when_enabled(client, db_session, admin_user, main_branch):
    # bir_reports now defaults OFF (registry flip, chore/bir-reports-default-off), so this
    # "when_enabled" case must explicitly enable it rather than relying on the old default.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:bir_reports', '1')
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
