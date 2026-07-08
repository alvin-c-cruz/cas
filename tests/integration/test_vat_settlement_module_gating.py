import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_404_when_bir_reports_disabled(client, db_session, main_branch, admin_user):
    login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '0'); clear_module_config_cache()
    assert client.get('/vat-settlement').status_code == 404
    assert client.get('/reports/bir/vat-return?year=2025&quarter=3').status_code == 404


def test_accessible_when_bir_reports_enabled(client, db_session, main_branch, admin_user):
    login(client)
    AppSettings.set_setting('module_enabled:bir_reports', '1'); clear_module_config_cache()
    assert client.get('/vat-settlement').status_code == 200
    assert client.get('/reports/bir/vat-return?year=2025&quarter=3').status_code == 200
