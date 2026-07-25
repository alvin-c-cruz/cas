"""Products list gets an 'All' tab plus one tab per active Product Category,
each panel showing only that category's products (owner directive 2026-07-25)."""
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
class TestProductsListCategoryTabs:
    def test_all_tab_and_one_tab_per_active_category(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        plastic = ProductCategory(code='PLASTIC', name='Plastic', is_active=True)
        tincan = ProductCategory(code='TINCAN', name='Tincan', is_active=True)
        inactive_cat = ProductCategory(code='OLD', name='Old Category', is_active=False)
        db.session.add_all([plastic, tincan, inactive_cat])
        db.session.commit()

        p1 = Product(code='P1', name='Pail', category_id=plastic.id)
        p2 = Product(code='T1', name='Can', category_id=tincan.id)
        p3 = Product(code='P2', name='Uncategorized Widget')
        db.session.add_all([p1, p2, p3])
        db.session.commit()

        _login(client, admin_user, main_branch)
        resp = client.get('/products')
        assert resp.status_code == 200
        html = resp.data.decode()

        # tab buttons
        assert 'data-tab-group="products"' in html
        assert 'data-tab="all"' in html
        assert f'data-tab="cat-{plastic.id}"' in html
        assert f'data-tab="cat-{tincan.id}"' in html
        # inactive category gets no tab
        assert f'data-tab="cat-{inactive_cat.id}"' not in html

        # panels exist
        assert 'data-tab-panel="products"' in html
        assert f'id="products-all"' in html
        assert f'id="products-cat-{plastic.id}"' in html
        assert f'id="products-cat-{tincan.id}"' in html

    def test_all_panel_contains_every_product(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        plastic = ProductCategory(code='PLASTIC', name='Plastic', is_active=True)
        db.session.add(plastic)
        db.session.commit()
        p1 = Product(code='P1', name='Pail', category_id=plastic.id)
        p2 = Product(code='P2', name='Uncategorized Widget')
        db.session.add_all([p1, p2])
        db.session.commit()

        _login(client, admin_user, main_branch)
        resp = client.get('/products')
        html = resp.data.decode()
        all_start = html.index('id="products-all"')
        all_end = html.index('</table>', all_start)
        all_panel = html[all_start:all_end]
        assert 'Pail' in all_panel
        assert 'Uncategorized Widget' in all_panel

    def test_category_panel_shows_only_its_own_products(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        plastic = ProductCategory(code='PLASTIC', name='Plastic', is_active=True)
        tincan = ProductCategory(code='TINCAN', name='Tincan', is_active=True)
        db.session.add_all([plastic, tincan])
        db.session.commit()
        p1 = Product(code='P1', name='PailOnly', category_id=plastic.id)
        p2 = Product(code='T1', name='CanOnly', category_id=tincan.id)
        db.session.add_all([p1, p2])
        db.session.commit()

        _login(client, admin_user, main_branch)
        resp = client.get('/products')
        html = resp.data.decode()

        plastic_start = html.index(f'id="products-cat-{plastic.id}"')
        plastic_end = html.index('</table>', plastic_start)
        plastic_panel = html[plastic_start:plastic_end]
        assert 'PailOnly' in plastic_panel
        assert 'CanOnly' not in plastic_panel

        tincan_start = html.index(f'id="products-cat-{tincan.id}"')
        tincan_end = html.index('</table>', tincan_start)
        tincan_panel = html[tincan_start:tincan_end]
        assert 'CanOnly' in tincan_panel
        assert 'PailOnly' not in tincan_panel

    def test_no_categories_renders_without_tabs(
        self, client, admin_user, main_branch, products_module_enabled
    ):
        """With zero active categories, the page falls back to the plain list --
        no tab bar clutter for an app that isn't using categories at all."""
        p1 = Product(code='P1', name='Solo Widget')
        db.session.add(p1)
        db.session.commit()

        _login(client, admin_user, main_branch)
        resp = client.get('/products')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'data-tab-group="products"' not in html
        assert 'Solo Widget' in html
