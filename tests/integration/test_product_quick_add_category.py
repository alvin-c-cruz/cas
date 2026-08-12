"""The shared product quick-add modal must offer a Category when one is required.

`products/views.py` swaps `category_id` to DataRequired whenever the
`product_categories` module is enabled, but `products/_quick_add_modal.html`
rendered no category field at all. Every "+ Add Product" on every transaction
form therefore returned {"ok": false, "errors": {"category_id": "Category is
required."}} and could never create a product.

The modal is a SHARED partial, so this was live on Accounts Payable, Sales
Invoice, CDV, CRV, Sales Orders and Quotations simultaneously.

The two POST tests below are the load-bearing ones: a render test alone would
still pass if the select were named something the view does not read.
"""
import pytest

from app.product_categories.models import ProductCategory

pytestmark = [pytest.mark.integration]

CAT_CODE = 'ZCAT9'
CAT_NAME = 'Probe Category A & B'


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _set_modules(db_session, value, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', value)
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def category(db_session):
    from app.utils.cache_helpers import clear_product_category_cache
    c = ProductCategory(code=CAT_CODE, name=CAT_NAME, is_active=True)
    db_session.add(c)
    db_session.commit()
    clear_product_category_cache()
    return c


@pytest.fixture
def ap_form(client, db_session, admin_user, main_branch, category):
    """Accounts Payable, deliberately -- NOT the Purchase Request form. The
    partial is shared, so proving it on a form this task never edited is what
    shows the fix reaches all six other consumers."""
    _set_modules(db_session, '1', 'products', 'product_categories')
    _login(client, admin_user, main_branch)
    resp = client.get('/accounts-payable/create')
    assert resp.status_code == 200
    return resp.data


class TestCategoryFieldRendered:

    def test_modal_offers_a_category_select(self, ap_form):
        assert b'name="category_id"' in ap_form

    def test_category_select_lists_active_categories(self, ap_form, category):
        html = ap_form.decode()
        assert f'value="{category.id}"' in html
        assert CAT_CODE in html

    def test_category_absent_when_module_off(self, client, db_session, admin_user,
                                             main_branch, category):
        """Control. With product_categories off the view relaxes category_id back
        to Optional(), so demanding one would block a create that the server would
        happily accept."""
        _set_modules(db_session, '1', 'products')
        _set_modules(db_session, '0', 'product_categories')
        _login(client, admin_user, main_branch)

        data = client.get('/accounts-payable/create').data
        assert b'name="category_id"' not in data


class TestNoCategoriesDefinedYet:
    """philgen has the module ON and ZERO categories. A required select with no
    options is a dead end -- every field fillable, submission always refused, no
    way to comply. Say so and disable Create instead."""

    @pytest.fixture
    def form_no_categories(self, client, db_session, admin_user, main_branch):
        from app.utils.cache_helpers import clear_product_category_cache
        ProductCategory.query.delete()
        db_session.commit()
        clear_product_category_cache()
        _set_modules(db_session, '1', 'products', 'product_categories')
        _login(client, admin_user, main_branch)
        resp = client.get('/accounts-payable/create')
        assert resp.status_code == 200
        return resp.data

    def test_explains_why_instead_of_showing_an_empty_required_select(
            self, form_no_categories):
        assert b'none have been set up yet' in form_no_categories
        assert b'id="pqa_category"' not in form_no_categories

    def test_create_button_is_disabled(self, form_no_categories):
        html = form_no_categories.decode()
        i = html.index('id="productQuickAddSubmit"')
        assert 'disabled' in html[i:i + 120]

    def test_create_button_is_enabled_once_a_category_exists(self, ap_form):
        """Control: the disable must be conditional, not permanent."""
        html = ap_form.decode()
        i = html.index('id="productQuickAddSubmit"')
        assert 'disabled' not in html[i:i + 120]


class TestQuickAddPostRoundTrip:
    """The render tests above pass even if the field carries the wrong NAME.
    These two do not."""

    def test_quick_add_succeeds_with_a_category(self, client, db_session,
                                                admin_user, main_branch, category):
        _set_modules(db_session, '1', 'products', 'product_categories')
        _login(client, admin_user, main_branch)

        resp = client.post('/products/create',
                           data={'code': 'ZQA01', 'name': 'Quick Add Probe',
                                 'is_active': '1', 'category_id': str(category.id),
                                 'default_unit_of_measure_id': '',
                                 'default_account_id': '', 'default_unit_price': ''},
                           headers={'X-Requested-With': 'XMLHttpRequest'})

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['ok'] is True
        assert body['product']['code'] == 'ZQA01'

    def test_quick_add_still_refuses_a_missing_category(self, client, db_session,
                                                        admin_user, main_branch,
                                                        category):
        """The bug this fixes must stay fixed in ONE direction only: the field is
        supplied, not the requirement removed. If someone 'fixes' it by dropping
        the DataRequired instead, this fails."""
        _set_modules(db_session, '1', 'products', 'product_categories')
        _login(client, admin_user, main_branch)

        resp = client.post('/products/create',
                           data={'code': 'ZQA02', 'name': 'No Category Probe',
                                 'is_active': '1', 'category_id': '',
                                 'default_unit_of_measure_id': '',
                                 'default_account_id': '', 'default_unit_price': ''},
                           headers={'X-Requested-With': 'XMLHttpRequest'})

        assert resp.status_code == 400
        assert 'category' in str(resp.get_json()['errors']).lower()
