"""A product name that already exists is refused.

Owner, 2026-09-23/25: `EPSON LQ-310 DOT MATRIX PRINTER` was entered twice (ids 615 and 617),
55 minutes apart by the same user -- not a double-submit, a person who was never told it
already existed. Investigation: there was NO duplicate check anywhere, and the full form and
the line pickers' quick-add post to the same route, so one validator on ProductForm covers
both. Owner's choice: BLOCK outright, no override.

Names compare case-insensitively with whitespace collapsed, against active AND inactive
products (an inactive twin should be reactivated, not re-entered). On EDIT the check runs only
when the name is actually changed, so the duplicates that already exist stay editable.
"""
import pytest

from app import db
from app.products.models import Product
from tests.integration.test_products_crud import _login, products_module_enabled  # noqa: F401

pytestmark = [pytest.mark.integration]

EPSON = 'EPSON LQ-310 DOT MATRIX PRINTER'


def _form(name, **extra):
    data = {'name': name, 'description': '', 'default_unit_of_measure_id': '',
            'default_unit_price': '', 'default_account_id': '', 'is_active': '1'}
    data.update(extra)
    return data


def _product(name, active=True):
    p = Product(name=name, is_active=active)
    db.session.add(p); db.session.commit()
    return p


class TestCreate:

    @pytest.mark.parametrize('typed', [EPSON, 'epson lq-310 dot matrix printer',
                                       '  Epson   LQ-310  Dot Matrix Printer '])
    def test_an_existing_name_is_refused(self, client, db_session, admin_user, main_branch,
                                         products_module_enabled, typed):
        _product(EPSON)
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data=_form(typed), follow_redirects=True)
        assert b'already exists' in resp.data
        assert Product.query.count() == 1

    def test_an_inactive_twin_is_named_as_inactive(self, client, db_session, admin_user,
                                                   main_branch, products_module_enabled):
        _product(EPSON, active=False)
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data=_form(EPSON), follow_redirects=True)
        assert b'already exists' in resp.data and b'inactive' in resp.data
        assert Product.query.count() == 1

    def test_the_quick_add_gets_the_error_as_json(self, client, db_session, admin_user,
                                                  main_branch, products_module_enabled):
        """The line pickers' '+ Add Product' posts here with XHR; its modal shows errors.name."""
        _product(EPSON)
        _login(client, admin_user, main_branch)
        resp = client.post('/products/create', data=_form(EPSON),
                           headers={'X-Requested-With': 'XMLHttpRequest'})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['ok'] is False and 'already exists' in body['errors']['name']
        assert Product.query.count() == 1

    def test_a_different_name_is_still_created(self, client, db_session, admin_user,
                                               main_branch, products_module_enabled):
        """CONTROL: the validator refuses duplicates, not products."""
        _product(EPSON)
        _login(client, admin_user, main_branch)
        client.post('/products/create', data=_form('EPSON LQ-590 DOT MATRIX PRINTER'),
                    follow_redirects=True)
        assert Product.query.count() == 2


class TestEdit:

    def test_renaming_into_an_existing_name_is_refused(self, client, db_session, admin_user,
                                                       main_branch, products_module_enabled):
        _product(EPSON)
        other = _product('SPIN DRYER')
        _login(client, admin_user, main_branch)
        resp = client.post(f'/products/{other.id}/edit', data=_form(EPSON.lower()),
                           follow_redirects=True)
        assert b'already exists' in resp.data
        assert db.session.get(Product, other.id).name == 'SPIN DRYER'

    def test_an_existing_duplicate_stays_editable(self, client, db_session, admin_user,
                                                  main_branch, products_module_enabled):
        """Duplicates that predate the rule (philgen has some) must not become un-editable:
        saving without changing the name is allowed."""
        _product(EPSON)
        twin = _product(EPSON)
        _login(client, admin_user, main_branch)
        client.post(f'/products/{twin.id}/edit', data=_form(EPSON, default_unit_price='150.00'),
                    follow_redirects=True)
        assert db.session.get(Product, twin.id).default_unit_price == 150

    def test_changing_only_the_case_of_its_own_name_is_allowed(self, client, db_session,
                                                               admin_user, main_branch,
                                                               products_module_enabled):
        p = _product('spin dryer')
        _login(client, admin_user, main_branch)
        client.post(f'/products/{p.id}/edit', data=_form('SPIN DRYER'), follow_redirects=True)
        assert db.session.get(Product, p.id).name == 'SPIN DRYER'
