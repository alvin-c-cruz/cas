"""Product.category_id becomes required once the product_categories module is
enabled; stays optional when it is not (owner directive 2026-07-25)."""
import pytest
from app import db
from app.products.models import Product
from app.product_categories.models import ProductCategory


@pytest.fixture
def products_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


@pytest.fixture
def product_categories_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:product_categories', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture(autouse=True)
def _fresh_category_cache(db_session):
    """get_active_product_categories() is memoized app-wide (Flask-Caching); a test
    run earlier in the same session can leave a stale list cached that doesn't
    reflect THIS test's own categories. Clear before and after every test here."""
    from app.utils.cache_helpers import clear_product_category_cache
    clear_product_category_cache()
    yield
    clear_product_category_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.mark.integration
class TestCategoryRequiredWhenModuleEnabled:
    def test_category_required_when_module_enabled(
        self, client, admin_user, main_branch, products_module_enabled, product_categories_module_enabled
    ):
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data={
            'code': 'P-NOCAT', 'name': 'No Category Widget', 'description': '',
            'default_unit_of_measure_id': '', 'default_account_id': '',
            'category_id': '', 'default_unit_price': '', 'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Product.query.filter_by(code='P-NOCAT').first() is None
        assert b'Category' in resp.data

    def test_category_optional_when_module_not_enabled(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        # product_categories module NOT enabled here -- category_id must stay optional
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data={
            'code': 'P-NOCAT2', 'name': 'Freeform Widget', 'description': '',
            'default_unit_of_measure_id': '', 'default_account_id': '',
            'category_id': '', 'default_unit_price': '', 'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        p = Product.query.filter_by(code='P-NOCAT2').first()
        assert p is not None
        assert p.category_id is None

    def test_category_still_savable_when_module_enabled(
        self, client, admin_user, main_branch, products_module_enabled, product_categories_module_enabled
    ):
        cat = ProductCategory(code='CATX', name='Category X', is_active=True)
        db.session.add(cat)
        db.session.commit()
        from app.utils.cache_helpers import clear_product_category_cache
        clear_product_category_cache()
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data={
            'code': 'P-HASCAT', 'name': 'Has Category Widget', 'description': '',
            'default_unit_of_measure_id': '', 'default_account_id': '',
            'category_id': str(cat.id), 'default_unit_price': '', 'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        p = Product.query.filter_by(code='P-HASCAT').one()
        assert p.category_id == cat.id

    def test_category_field_shows_required_asterisk_when_module_enabled(
        self, client, admin_user, main_branch, products_module_enabled, product_categories_module_enabled
    ):
        _login(client, admin_user, main_branch)
        resp = client.get('/products/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        cat_label_idx = html.index('for="category_id"')
        snippet = html[cat_label_idx:cat_label_idx + 200]
        assert 'required' in snippet

    def test_category_field_no_asterisk_when_module_disabled(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        _login(client, admin_user, main_branch)
        resp = client.get('/products/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        cat_label_idx = html.index('for="category_id"')
        snippet = html[cat_label_idx:cat_label_idx + 200]
        assert 'required' not in snippet
