"""Integration tests for Product Category CRUD."""
import pytest
from app import db
from app.product_categories.models import ProductCategory
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


@pytest.fixture
def product_categories_module_enabled(db_session):
    """Enable the optional product_categories module for the duration of the test.

    product_categories is default_enabled=False (optional); tests that hit its
    endpoints need it enabled or the before_request module gate 404s them. Clears
    the memoize cache on setup and teardown so the enabled state does not bleed
    into other tests that assert the default-off behaviour (mirrors
    uom_module_enabled in test_units_of_measure_crud.py).
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:product_categories', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


class TestProductCategoriesCrud:
    def test_create_persists_and_audits(self, client, admin_user, main_branch, login_user,
                                        product_categories_module_enabled):
        login_user(client, 'admin', 'admin123')
        resp = client.post('/product-categories/create',
                           data={'code': 'BEV', 'name': 'Beverages', 'is_active': '1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        c = ProductCategory.query.filter_by(code='BEV').one()
        assert c.name == 'Beverages'
        entry = AuditLog.query.filter_by(module='product_categories', action='create',
                                         record_id=c.id).one()
        assert entry.record_identifier == 'BEV'

    def test_edit_updates_and_audits(self, client, admin_user, main_branch, login_user,
                                     product_categories_module_enabled):
        login_user(client, 'admin', 'admin123')
        c = ProductCategory(code='SNK', name='Snacks', is_active=True)
        db.session.add(c)
        db.session.commit()
        resp = client.post(f'/product-categories/{c.id}/edit',
                           data={'code': 'SNK', 'name': 'Snack Foods', 'is_active': '1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(c)
        assert c.name == 'Snack Foods'
        assert AuditLog.query.filter_by(module='product_categories', action='update',
                                        record_id=c.id).count() == 1

    def test_list_renders(self, client, admin_user, main_branch, login_user,
                          product_categories_module_enabled):
        login_user(client, 'admin', 'admin123')
        db.session.add(ProductCategory(code='BEV', name='Beverages'))
        db.session.commit()
        resp = client.get('/product-categories')
        assert resp.status_code == 200
        assert b'Beverages' in resp.data

    def test_staff_cannot_create(self, client, staff_user, main_branch, login_user,
                                 product_categories_module_enabled):
        staff_user.set_branches([main_branch])
        db.session.commit()
        login_user(client, 'staff', 'staff123')
        resp = client.post('/product-categories/create',
                           data={'code': 'X', 'name': 'X', 'is_active': '1'},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert ProductCategory.query.filter_by(code='X').first() is None
