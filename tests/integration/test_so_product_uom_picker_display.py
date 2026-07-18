"""Regression tests for BUG-SO-PRODUCT-UOM-FIELD-DISPLAY: Product/UOM pickers on the Sales
Order form must (a) use the app-standard "code: name" option separator (not "code -- name"),
and (b) be wrapped with Choices.js so the committed value shows just the name."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_product_option_uses_colon_separator(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert "escHtml(p.code)}: ${escHtml(p.name)" in body, (
        'Product option template must use "code: name" (colon), matching UOM\'s '
        'existing separator convention')
    assert "escHtml(p.code)} — ${escHtml(p.name)" not in body, (
        'Product option template must not use the old em-dash separator')


def test_product_and_uom_selects_get_choices_js_name_only_template(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'prod-sel-${id}' in body, 'Product select needs an id to wire Choices.js onto'
    assert 'new Choices(prodSelEl' in body or 'new Choices(prodSel' in body, (
        'Product select must be wrapped with Choices.js')
    assert 'new Choices(uomSelEl' in body or 'new Choices(uomSel' in body, (
        'UOM select must be wrapped with Choices.js')
    assert 'data.customProperties && data.customProperties.name' in body, (
        'the item template must render the NAME (not the code) once a value is committed')
