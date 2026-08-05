"""A validation failure on Sales Order CREATE must not throw away the user's lines.

BUG-SO-CREATE-ERROR-DISCARDS-ALL-LINES: every error path in create() re-rendered
the form with `line_items=[]` hardcoded, so a duplicate SO number -- an ordinary
typo, since SO numbers are typed by the user -- cost the whole order. On RIC that
is up to nine lines retyped. edit() and amend() already restore the submitted
lines via `restore_items`; create() simply never did.

These are RENDER assertions, deliberately. The lines reach the browser through
`const existingItems = {{ line_items | tojson }}`, so the test reads what the
template actually emitted. A POST-contract test cannot see a dropped re-render --
the same reasoning as csrf-only-render-drops-hidden-fields.
"""
import json
import pytest

from app import db
from app.sales_orders.models import SalesOrder

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _two_lines(product):
    return json.dumps([
        {'product_id': product.id, 'quantity': '10', 'unit_price': '25.00',
         'amount': '250.00', 'vat_rate': '12', 'uom_text': 'PCS'},
        {'product_id': product.id, 'quantity': '7', 'unit_price': '30.00',
         'amount': '210.00', 'vat_rate': '12', 'uom_text': 'PCS'},
    ])


def _post(client, customer, product, so_number, **over):
    data = {
        'so_number': so_number,
        'order_date': '2026-08-05',
        'customer_id': str(customer.id),
        'payment_terms': 'Net 30',
        'notes': '',
        'line_items': _two_lines(product),
    }
    data.update(over)
    return client.post('/sales-orders/create', data=data, follow_redirects=True)


def _rendered_lines(html):
    """The line array the template handed to the browser."""
    marker = 'const existingItems = '
    if marker not in html:
        return []
    blob = html.split(marker, 1)[1]
    blob = blob[:blob.index(';\n')] if ';\n' in blob else blob.split(';')[0]
    try:
        return json.loads(blob)
    except ValueError:
        return []


@pytest.fixture
def setup(client, db_session, main_branch, accountant_user):
    _enable_products(db_session)
    cust = _customer(db_session)
    prod = _product(db_session)
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    return cust, prod


def test_duplicate_so_number_keeps_the_lines(client, db_session, main_branch,
                                             accountant_user, setup):
    """The reported case."""
    cust, prod = setup
    existing = SalesOrder(branch_id=main_branch.id, so_number='SO-DUP-1',
                          order_date=db.func.current_date(), customer_id=cust.id,
                          customer_name=cust.name, notes='', status='draft',
                          created_by_id=accountant_user.id)
    db_session.add(existing)
    db_session.commit()

    resp = _post(client, cust, prod, 'SO-DUP-1')
    html = resp.data.decode()
    assert b'already exists' in resp.data, 'expected the duplicate refusal'
    lines = _rendered_lines(html)
    assert len(lines) == 2, 'both submitted lines must survive the refusal, got %r' % lines
    assert str(lines[0].get('quantity')) in ('10', '10.0')
    assert str(lines[1].get('quantity')) in ('7', '7.0')


def test_blank_so_number_keeps_the_lines(client, setup):
    cust, prod = setup
    resp = _post(client, cust, prod, '   ')
    assert b'SO number is required' in resp.data
    assert len(_rendered_lines(resp.data.decode())) == 2


def test_invalid_customer_keeps_the_lines(client, setup):
    cust, prod = setup
    resp = _post(client, cust, prod, 'SO-NEW-1', customer_id='0')
    assert b'customer' in resp.data.lower()
    assert len(_rendered_lines(resp.data.decode())) == 2


def test_a_malformed_line_payload_does_not_500(client, setup):
    """The restore path parses submitted JSON, so a crafted body must not take the
    form down -- it should re-render empty rather than raise."""
    cust, prod = setup
    resp = _post(client, cust, prod, '   ', line_items='{not json at all')
    assert resp.status_code == 200


def test_a_valid_create_still_works(client, db_session, setup):
    """Control: the fix must not disturb the happy path."""
    cust, prod = setup
    resp = _post(client, cust, prod, 'SO-OK-1')
    assert b'created successfully' in resp.data
    so = SalesOrder.query.filter_by(so_number='SO-OK-1').first()
    assert so is not None and len(so.line_items) == 2
