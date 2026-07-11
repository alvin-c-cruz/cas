"""BUG-QUOTE-LINE-NO-PRODUCT-UOM: a quotation line must reference a product
(owner-directed 2026-07-11d). The quote parser is meant to mirror
sales_orders._parse_and_attach_so_lines, which raises on a product-less line;
that guard was dropped for quotations, letting a bare qty/price line save with
product_id=NULL -- a line that identifies nothing.
"""
import json
import pytest

from app import db
from app.customers.models import Customer
from app.products.models import Product

pytestmark = [pytest.mark.integration, pytest.mark.quotations]


@pytest.fixture(autouse=True)
def quotations_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('quotations', 'sales_orders', 'products', 'units_of_measure', 'employees'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _post(client, c, lines):
    return client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'inclusive', 'payment_terms': 'Net 30',
        'lines': json.dumps(lines)}, follow_redirects=True)


def test_product_less_line_is_rejected(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add(c); db.session.commit()
    _login(client, admin_user, main_branch)
    # qty + price, but NO product_id -> a line that identifies nothing.
    resp = _post(client, c, [{'quantity': '1', 'unit_price': '10000', 'amount': '10000'}])
    assert Quotation.query.filter_by(customer_id=c.id).first() is None   # not saved
    assert b'product' in resp.data.lower()                               # error surfaced


def test_line_with_product_is_accepted(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    _login(client, admin_user, main_branch)
    resp = _post(client, c, [{'product_id': str(p.id), 'quantity': '1',
                              'unit_price': '10000', 'amount': '10000'}])
    q = Quotation.query.filter_by(customer_id=c.id).first()
    assert q is not None and q.line_items[0].product_id == p.id
