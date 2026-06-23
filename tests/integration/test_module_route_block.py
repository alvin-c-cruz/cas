import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def test_bir_route_200_when_enabled(client, db_session, admin_user, main_branch):
    # /reports/bir redirects to the under_development page (no BIR template yet);
    # follow_redirects=True lands at the 200 under-development page, confirming the
    # endpoint is reachable (not 404'd) when the module is enabled.
    _login(client)
    resp = client.get('/reports/bir', follow_redirects=True)
    assert resp.status_code == 200


def test_bir_route_404_when_disabled_even_for_admin(client, db_session, admin_user, main_branch):
    # Disabling the BIR module must abort(404) BEFORE any redirect or template render,
    # even when the requesting user is admin.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '0')
    clear_module_config_cache()
    resp = client.get('/reports/bir', follow_redirects=False)
    assert resp.status_code == 404
