"""BUG-SO-QTY-NO-FORMATTING / BUG-SO-UNITPRICE-NO-FORMATTING: the SO form's
per-line Quantity and Unit Price inputs must use the same focus/blur
formatting pattern the Amount field already has."""
import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_create_form_wires_qty_and_price_focus_blur(client, db_session, staff_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    staff_user.branches.append(main_branch)
    perms = staff_user.get_book_permissions()
    perms['sales_orders'] = True
    staff_user.set_book_permissions(perms)
    db_session.commit()
    clear_module_config_cache()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/sales-orders/create')
    body = resp.get_data(as_text=True)
    assert 'onblur="soQtyBlur(this, ${id})"' in body
    assert 'onfocus="soQtyFocus(this)"' in body
    assert 'onblur="upBlur(this, ${id})"' in body
    assert "id=\"qty-${id}\" class=\"form-control\" type=\"text\"" in body.replace("class=\"form-control\"\n                   style", "class=\"form-control\" style") or 'id="qty-${id}"' in body


def test_so_qty_fmt_function_present_with_whole_unit_uom_list(client, db_session, staff_user, main_branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    staff_user.branches.append(main_branch)
    perms = staff_user.get_book_permissions()
    perms['sales_orders'] = True
    staff_user.set_book_permissions(perms)
    db_session.commit()
    clear_module_config_cache()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/sales-orders/create')
    body = resp.get_data(as_text=True)
    assert 'function soQtyFmt' in body
    assert "'PCS'" in body or '"PCS"' in body
