"""The PR form's product/UOM pickers carry inline "+ Add" quick-add actions.

Render assertions on the GET. The wiring is entirely markup + inline JS -- the
modal partial, the quick-add script, and the addAction options -- so a POST
contract test cannot observe any of it.

PR is the first consumer of search-select.js's built-in `addAction` (AP and SI
predate it and hand-roll an `__add_product__` <option> plus a change listener).
The built-in keeps the action reachable when the search filter would drop it,
which is precisely when you want to add something.
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


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


def _get_form(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    return resp.data


@pytest.fixture
def form_all_on(client, db_session, admin_user, main_branch):
    _set_modules(db_session, '1', 'products', 'units_of_measure',
                 'purchase_orders', 'purchase_requests')
    return _get_form(client, db_session, admin_user, main_branch)


class TestQuickAddWiring:

    def test_product_quick_add_modal_is_included(self, form_all_on):
        assert b'productQuickAddOverlay' in form_all_on
        assert b'productQuickAddForm' in form_all_on

    def test_uom_quick_add_modal_is_included(self, form_all_on):
        assert b'uomQuickAddOverlay' in form_all_on
        assert b'uomQuickAddForm' in form_all_on

    def test_quick_add_scripts_are_loaded(self, form_all_on):
        assert b'product-quick-add.js' in form_all_on
        assert b'uom-quick-add.js' in form_all_on

    def test_add_actions_are_labelled(self, form_all_on):
        assert b'+ Add Product' in form_all_on
        assert b'+ Add UOM' in form_all_on

    def test_quick_add_initialisers_run_before_the_first_row(self, form_all_on):
        """Each row's addAction closure calls openProductModal/openUomModal, which
        only exist once init*QuickAdd() has run."""
        html = form_all_on.decode()
        assert html.index('initProductQuickAdd()') < html.index('.forEach(addRow)')
        assert html.index('initUomQuickAdd()') < html.index('.forEach(addRow)')

    def test_serialiser_refuses_the_add_sentinels(self, form_all_on):
        """`__add_product__` is a real <option> value in the select. If it were
        ever current at submit time it would be POSTed where an integer product
        id belongs."""
        html = form_all_on.decode()
        assert 'realValue' in html
        assert 'product_id: realValue(' in html
        assert 'uom_id: realValue(' in html


class TestQuickAddIsModuleGated:
    """Control tests. Without these, wiring the action unconditionally would pass
    every assertion above while offering to create a product on an instance where
    the products module is off and products.create is not reachable."""

    def test_product_quick_add_absent_when_products_module_off(
            self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, '1', 'units_of_measure', 'purchase_orders',
                     'purchase_requests')
        _set_modules(db_session, '0', 'products')
        data = _get_form(client, db_session, admin_user, main_branch)

        assert b'productQuickAddOverlay' not in data
        assert b'product-quick-add.js' not in data
        assert b'+ Add Product' not in data

    def test_uom_quick_add_absent_when_uom_module_off(
            self, client, db_session, admin_user, main_branch):
        _set_modules(db_session, '1', 'products', 'purchase_orders',
                     'purchase_requests')
        _set_modules(db_session, '0', 'units_of_measure')
        data = _get_form(client, db_session, admin_user, main_branch)

        assert b'uomQuickAddOverlay' not in data
        assert b'uom-quick-add.js' not in data
        assert b'+ Add UOM' not in data
