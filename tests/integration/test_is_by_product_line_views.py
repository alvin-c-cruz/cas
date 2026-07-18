"""Integration tests for the Income Statement by Product Line report routes."""
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def test_404_when_module_disabled(client, admin_user, main_branch, login_user):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:income_statement_by_product_line', '0')
    db.session.commit()
    clear_module_config_cache()
    login_user(client, 'admin', 'admin123')
    resp = client.get('/reports/income-statement-by-product-line')
    assert resp.status_code == 404
    clear_module_config_cache()
