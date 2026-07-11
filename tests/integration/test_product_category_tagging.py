"""Product gains an optional category (product line)."""
import pytest
from app import db
from app.products.models import Product
from app.product_categories.models import ProductCategory


@pytest.fixture
def products_module_enabled(db_session):
    """Enable the optional products module for the duration of the test.

    products is default_enabled=False (optional); tests that hit product endpoints
    need it enabled or the before_request hook aborts with 404 (products.list is not
    in EXEMPT_ENDPOINTS, only products.create is). Mirrors
    test_products_crud.py::products_module_enabled.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def _login(client, user, branch):
    """Log a user in and set a branch in the session (mirrors test_products_crud.py)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.mark.integration
class TestProductCategoryTagging:
    def test_product_carries_category(self, db_session):
        cat = ProductCategory(code='BEV', name='Beverages')
        db.session.add(cat)
        db.session.commit()
        p = Product(code='P1', name='Cola', category_id=cat.id)
        db.session.add(p)
        db.session.commit()
        assert p.category_id == cat.id
        assert p.category.code == 'BEV'
        assert p.to_dict()['category_id'] == cat.id

    def test_category_is_optional(self, db_session):
        p = Product(code='P2', name='Freeform')
        db.session.add(p)
        db.session.commit()
        assert p.category_id is None
        assert p.to_dict()['category_id'] is None

    def test_form_saves_category(self, client, admin_user, main_branch, products_module_enabled):
        _login(client, admin_user, main_branch)
        cat = ProductCategory(code='SNK', name='Snacks', is_active=True)
        db.session.add(cat)
        db.session.commit()
        resp = client.post('/products/create', data={
            'code': 'P3', 'name': 'Chips', 'description': '',
            'default_unit_of_measure_id': '', 'default_account_id': '',
            'category_id': str(cat.id), 'default_unit_price': '', 'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        p = Product.query.filter_by(code='P3').one()
        assert p.category_id == cat.id
