import pytest

pytestmark = [pytest.mark.integration]


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def test_bir_route_not_404_when_enabled(client, db_session, admin_user, main_branch):
    # When the BIR module is enabled, the endpoint passes the module gate and is reachable.
    # Assert only "not 404" (it 302-redirects to under_development today) so the test proves
    # the gate let it through WITHOUT coupling to the redirect target's status.
    # Clear the session-scoped enablement cache so a prior disable-test can't leak a stale value.
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache()
    _login(client)
    resp = client.get('/reports/bir', follow_redirects=False)
    assert resp.status_code != 404


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
