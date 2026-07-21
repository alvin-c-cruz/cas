"""App-wide master-data create-form submit button convention (2026-07-20, owner
directive): every master-data create form's in-form submit button reads
"Save {Record}" (was "Create {Record}", or bare "Create" for a handful of
modules that had no record noun at all -- those gained the noun in the same
pass). Edit-mode stays "Update {Record}", unchanged.

Note the page <title>/<h1> for a create form legitimately still says
"Create {Record}" (unaffected by this change -- only the in-form SUBMIT
BUTTON changed), so assertions here scope to the <button> element itself via
_submit_button_text(), not a page-wide substring check.

This is a mechanical sweep across every master-data module that did not
already have its own dedicated button-label test (accounts and vendors are
covered in test_account_form_button_label.py / test_vendor_views.py).
"""
import re
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable_module(key):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting(f'module_enabled:{key}', '1')
    db.session.commit()
    clear_module_config_cache()


def _submit_button_text(html):
    m = re.search(r'<button type="submit"[^>]*>\s*([^<]+?)\s*</button>', html)
    assert m is not None, 'no <button type="submit"> found in the response'
    return m.group(1).strip()


@pytest.mark.parametrize('url,expected', [
    ('/customers/create', 'Save Customer'),
    ('/vat-categories/create', 'Save Input VAT Category'),
    ('/sales-vat-categories/create', 'Save Sales VAT Category'),
    ('/withholding-tax/create', 'Save Withholding Tax'),
    ('/branches/create', 'Save Branch'),
])
def test_ungated_masterdata_create_form_says_save(client, db_session, admin_user,
                                                    main_branch, url, expected):
    """These modules are always-on (not optional/module-gated)."""
    _login(client, admin_user, main_branch)
    resp = client.get(url)
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == expected


def test_product_categories_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('product_categories')
    _login(client, admin_user, main_branch)
    resp = client.get('/product-categories/create')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Product Category'


def test_units_of_measure_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('units_of_measure')
    _login(client, admin_user, main_branch)
    resp = client.get('/units-of-measure/create')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Unit of Measure'


def test_products_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('units_of_measure')
    _enable_module('products')
    _login(client, admin_user, main_branch)
    resp = client.get('/products/create')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Product'


def test_work_centers_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('work_centers')
    _login(client, admin_user, main_branch)
    resp = client.get('/work-centers/create')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Work Center'


def test_fixed_asset_categories_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('fixed_assets')
    _login(client, admin_user, main_branch)
    resp = client.get('/fixed-assets/categories/create')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Asset Category'


def test_bank_accounts_create_form_says_save(client, db_session, admin_user, main_branch):
    _enable_module('bank_accounts')
    _login(client, admin_user, main_branch)
    resp = client.get('/bank-accounts/new')
    assert resp.status_code == 200
    assert _submit_button_text(resp.data.decode()) == 'Save Bank Account'
