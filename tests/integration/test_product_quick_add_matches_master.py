"""PROD-QA: the inline "Add product" box takes the same fields as the Products master form.

Owner, 22 Nov 2026 12:12 PH, on the SO form's "Add product" box: "report this to products session. the two should be
identical". The box took 3 of the master's fields (Category, Name, Price). It now renders the master's own field
template (products/_form_fields.html), as the customer and vendor boxes already do, so the two cannot drift apart.
The box's fields carry the prefix "pqa-" so they never repeat an id of the page around them; product-quick-add.js
takes the prefix off before posting to the same view the master form posts to.
Work order: app-docs/bug-reports/2026-11-22-product-quick-add-matches-master.md.
"""
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]

#: The Products master form's fields, in the order the page shows them (inventory module off).
MASTER = ['name', 'customer_code', 'description', 'job_order_name', 'default_unit_of_measure_id', 'default_account_id',
          'allowed_unit_ids', 'category_id', 'default_unit_price', 'standard_cost', 'inventory_unit_id',
          'inventory_qty_per_unit', 'is_active']
#: With the inventory module on, three more before the status.
MASTER_INVENTORY = MASTER[:-1] + ['track_inventory', 'costing_method', 'reorder_level', 'is_active']

#: The eight forms that carry the box, and the modules each needs.
FORMS = [
    ('/accounts-payable/create', ()),
    ('/cash-disbursements/create', ()),
    ('/cash-receipts/create', ()),
    ('/purchase-orders/create', ('purchase_orders',)),
    ('/purchase-requests/create', ('purchase_requests',)),
    ('/quotations/create', ('quotations',)),
    ('/sales-invoices/create', ()),
    ('/sales-orders/create', ('sales_orders',)),
]


@pytest.fixture(autouse=True)
def _leave_no_cache_behind():
    """These tests switch modules on and fill the app's cached lists; a later test in the same worker must not see
    them (the session-long app cache outlives each test's database)."""
    yield
    from app import cache
    cache.clear()


def _modules(db_session, *keys):
    from app import cache
    for key in keys:
        AppSettings.set_setting(f'module_enabled:{key}', '1')
    db_session.commit()
    cache.clear()                      # module switches and the cached lists of units, accounts, categories


def _signed_in(client, admin_user, main_branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id


def _names(html):
    """The form fields' names, in page order, once each (a multiple select posts one name)."""
    seen = []
    for n in re.findall(r'<(?:input|select|textarea)\b[^>]*\bname="([^"]+)"', html):
        if n not in seen and not n.endswith('csrf_token'):
            seen.append(n)
    return seen


def _labels(html):
    return [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', t)).strip()
            for t in re.findall(r'<label\b[^>]*>(.*?)</label>', html, re.S)]


def _master_form(html):
    return html[html.index('<form method="POST" novalidate>'):html.index('</form>')]


def _box(html):
    start = html.index('id="productQuickAddForm"')
    return html[start:html.index('</form>', start)]


@pytest.fixture
def things(db_session, make_account):
    from app.product_categories.models import ProductCategory
    from app.units_of_measure.models import UnitOfMeasure
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    kg = UnitOfMeasure(code='KG', name='Kilogram', is_active=True)
    cat = ProductCategory(code='MANGO', name='Mango', is_active=True)
    db.session.add_all([pc, kg, cat])
    db.session.commit()
    return pc, kg, cat, make_account('411001')


# --- the fields -------------------------------------------------------------------------------------------------------

def test_the_products_page_has_the_master_fields(client, db_session, admin_user, main_branch, things):
    _modules(db_session, 'products')
    _signed_in(client, admin_user, main_branch)
    assert _names(_master_form(client.get('/products/create').get_data(as_text=True))) == MASTER


@pytest.mark.parametrize('url, modules', FORMS)
def test_the_box_on_each_form_has_the_same_fields_as_the_master(client, db_session, admin_user, main_branch, things,
                                                                url, modules):
    _modules(db_session, 'products', *modules)
    _signed_in(client, admin_user, main_branch)
    resp = client.get(url)
    assert resp.status_code == 200, url
    box = _box(resp.get_data(as_text=True))
    assert _names(box) == ['pqa-' + n for n in MASTER], url


def test_the_box_has_the_same_labels_as_the_master(client, db_session, admin_user, main_branch, things):
    _modules(db_session, 'products', 'sales_orders')
    _signed_in(client, admin_user, main_branch)
    master = _labels(_master_form(client.get('/products/create').get_data(as_text=True)))
    box = _labels(_box(client.get('/sales-orders/create').get_data(as_text=True)))
    assert box == master and 'Name' in box and 'Allowed Units (no-PO receiving)' in box


def test_with_inventory_on_both_have_the_inventory_fields(client, db_session, admin_user, main_branch, things):
    _modules(db_session, 'products', 'inventory', 'sales_orders')
    _signed_in(client, admin_user, main_branch)
    assert _names(_master_form(client.get('/products/create').get_data(as_text=True))) == MASTER_INVENTORY
    assert _names(_box(client.get('/sales-orders/create').get_data(as_text=True))) == [
        'pqa-' + n for n in MASTER_INVENTORY]


@pytest.mark.parametrize('url, modules', FORMS)
def test_no_id_of_the_box_repeats_one_of_the_page(client, db_session, admin_user, main_branch, things, url, modules):
    _modules(db_session, 'products', 'inventory', *modules)
    _signed_in(client, admin_user, main_branch)
    html = client.get(url).get_data(as_text=True)
    ids = re.findall(r'\bid="([^"]+)"', _box(html))
    assert ids, url
    repeated = [i for i in ids if html.count(f'id="{i}"') != 1]
    assert repeated == [], (url, repeated)


def test_the_box_starts_active_with_nothing_chosen(client, db_session, admin_user, main_branch, things):
    _modules(db_session, 'products', 'sales_orders')
    _signed_in(client, admin_user, main_branch)
    box = _box(client.get('/sales-orders/create').get_data(as_text=True))
    assert re.search(r'<option[^>]*selected[^>]*value="1"|<option value="1" selected', box), 'status starts Active'
    unit = re.search(r'<select[^>]*name="pqa-default_unit_of_measure_id"[^>]*>(.*?)</select>', box, re.S).group(1)
    assert re.search(r'<option selected value="">', unit)                 # the blank "— None —"
    assert not re.search(r'<option selected value="\d+"', unit)           # no unit chosen for the user


# --- saving ------------------------------------------------------------------------------------------------------------

def _post(client, data, ajax):
    headers = {'X-Requested-With': 'XMLHttpRequest'} if ajax else {}
    return client.post('/products/create', data=data, headers=headers, follow_redirects=not ajax)


def _every_field(pc, kg, cat, account, name):
    return {'name': name, 'customer_code': 'CUST-77', 'description': 'Sold by the kilo.',
            'job_order_name': 'DRIED MANGO (JO)', 'default_unit_of_measure_id': str(pc.id),
            'default_account_id': str(account.id), 'allowed_unit_ids': [str(pc.id), str(kg.id)],
            'category_id': str(cat.id), 'default_unit_price': '790.00', 'standard_cost': '500.00',
            'inventory_unit_id': str(kg.id), 'inventory_qty_per_unit': '0.1', 'is_active': '1'}


def test_saving_from_the_box_stores_what_the_master_form_would(client, db_session, admin_user, main_branch, things):
    from app.products.models import Product
    pc, kg, cat, account = things
    _modules(db_session, 'products', 'product_categories')
    _signed_in(client, admin_user, main_branch)
    resp = _post(client, _every_field(pc, kg, cat, account, 'FROM THE BOX'), ajax=True)
    assert resp.status_code == 200 and resp.get_json()['ok'] is True
    _post(client, _every_field(pc, kg, cat, account, 'FROM THE MASTER'), ajax=False)
    box = Product.query.filter_by(name='FROM THE BOX').one().to_dict()
    master = Product.query.filter_by(name='FROM THE MASTER').one().to_dict()
    for d in (box, master):
        d.pop('id'), d.pop('name')
    assert box == master
    assert box['allowed_unit_ids'] == sorted([pc.id, kg.id]) and box['inventory_qty_per_unit'] == 0.1
    assert (box['default_uom_id'], box['default_account_id'], box['category_id']) == (pc.id, account.id, cat.id)


def test_the_box_gets_the_whole_product_back(client, db_session, admin_user, main_branch, things):
    from app.products.models import Product
    pc, kg, cat, account = things
    _modules(db_session, 'products', 'product_categories')
    _signed_in(client, admin_user, main_branch)
    product = _post(client, _every_field(pc, kg, cat, account, 'WHOLE'), ajax=True).get_json()['product']
    stored = Product.query.filter_by(name='WHOLE').one().to_dict()
    assert {k: product[k] for k in stored} == stored
    assert product['label'] == 'WHOLE' and product['unit_price'] == 790.0       # what the forms read before


def test_a_refusal_comes_back_by_field(client, db_session, admin_user, main_branch, things):
    _modules(db_session, 'products', 'product_categories')
    _signed_in(client, admin_user, main_branch)
    resp = _post(client, {'name': '', 'is_active': '1'}, ajax=True)
    assert resp.status_code == 400
    assert resp.get_json()['errors'] == {'name': 'Name is required.', 'category_id': 'Category is required.'}


# --- the page's script --------------------------------------------------------------------------------------------------

def _source(app, rel):
    return (Path(app.root_path) / rel).read_text(encoding='utf-8')


def test_the_box_script_posts_the_fields_without_their_prefix(app):
    js = _source(app, 'static/product-quick-add.js')
    assert "var PREFIX = 'pqa-';" in js
    assert 'fd.append(k.indexOf(PREFIX) === 0 ? k.slice(PREFIX.length) : k, v)' in js     # every value, multiples too
    assert "getElementById('pqa-name')" in js


@pytest.mark.parametrize('rel, push', [
    ('accounts_payable/templates/accounts_payable/form.html', 'products.push(p);'),
    ('cash_disbursements/templates/cash_disbursements/form.html', 'products.push(p);'),
    ('cash_receipts/templates/cash_receipts/form.html', 'products.push(p);'),
    ('purchase_orders/templates/purchase_orders/form.html', 'PRODUCTS.push(p);'),
    ('purchase_requests/templates/purchase_requests/form.html', 'PRODUCTS.push(p);'),
    ('quotations/templates/quotations/form.html', 'products.push(p);'),
    ('sales_invoices/templates/sales_invoices/form.html', 'products.push(p);'),
    ('sales_orders/templates/sales_orders/form.html', 'products.push(p);'),
])
def test_each_form_keeps_the_whole_new_product(app, rel, push):
    """The page's own product list gets the product as the server sent it, so a line takes its unit, allowed units,
    price, account and inventory factor as it would for a product loaded with the page."""
    src = _source(app, rel)
    callback = src[src.index('openProductModal('):]
    callback = callback[:callback.index('});')]
    assert push in callback, rel
