"""Regression test for BUG-SO-ADDLINE-VAT-NOT-INHERITED: a line added via the bare
addLineItem() call (no argument -- what the "+ Add Line" button uses) must inherit the
already-selected customer's default VAT category instead of defaulting to ''."""

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


def test_addlineitem_default_inherits_customer_vat_category(client, db_session, accountant_user, main_branch):
    """Test that addLineItem() with no argument defaults vat_category to the
    currently selected customer's default VAT category, not a hardcoded empty string."""
    from app.customers.models import Customer

    # Create a customer with a default VAT category
    customer = Customer(code='TEST01', name='Test Customer', is_active=True, default_vat_category='V12')
    db_session.add(customer)
    db_session.commit()

    # Login
    with client.session_transaction() as sess:
        sess['_user_id'] = str(accountant_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id

    # Request the create form
    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    # Assert the fix is present: addLineItem's default-object branch must default
    # vat_category to currentCustomerVatCategory, not a hardcoded ''
    # Looking for the fixed pattern inside the addLineItem function
    assert "vat_category: currentCustomerVatCategory || ''" in body, (
        "addLineItem's default-object branch must default vat_category to "
        "currentCustomerVatCategory, not a hardcoded ''")

    # Assert no other line-item object literal still hardcodes vat_category to ''
    # in the addLineItem function (the buggy pattern is: vat_category: '' } followed by semicolon)
    assert "vat_category: '' }" not in body, (
        "The default-object branch in addLineItem should not hardcode vat_category "
        "to an empty string")
