"""Saving a new Sales Order lands on that order's own EDIT FORM, not the list.

Owner directive 2026-08-31: "saving the SO should redirect to the form, not in
the list, so user can further edit the SO."

Read as the EDIT form rather than the detail page: the detail page is read-only,
so it cannot satisfy "so user can further edit". create() previously redirected
to sales_orders.list, which dropped the user out of the document entirely --
re-opening it took a list scan plus two clicks.

DELIBERATELY UNCHANGED, and asserted below so the change stays scoped:
  * edit() still returns to the DETAIL page on save. Saving an edit is finishing
    a change; saving a create is usually the middle of entering one. Making both
    land on the form would trap an editor in a loop with no obvious exit.
  * a REFUSED create still re-renders the form in place rather than redirecting,
    so the typed lines survive (test_so_create_error_keeps_lines covers the
    restore itself; here we only pin that no redirect appeared).
"""
import datetime
import json
import re

import pytest
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _payload(customer, product, so_number='SO-REDIR-1'):
    lines = json.dumps([{'product_id': str(product.id), 'quantity': '2',
                         'unit_price': '100.00', 'vat_category': None, 'vat_rate': '0'}])
    return {'so_number': so_number, 'order_date': '2026-08-31',
            'customer_id': str(customer.id), 'customer_name': customer.name,
            'payment_terms': 'Net 30', 'notes': '', 'line_items': lines}


@pytest.fixture
def ready(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    c = _customer(db_session)
    p = _product(db_session, code='RDR-1', name='Redirect Widget')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return c, p


def test_create_redirects_to_the_new_orders_edit_form(client, db_session, ready):
    c, p = ready
    resp = client.post('/sales-orders/create', data=_payload(c, p))

    assert resp.status_code == 302
    so = SalesOrder.query.filter_by(so_number='SO-REDIR-1').one()
    assert resp.headers['Location'].endswith(f'/sales-orders/{so.id}/edit'), \
        resp.headers['Location']


def test_the_landing_page_is_that_orders_editable_form(client, db_session, ready):
    """Following the redirect must reach a FORM for the order just saved -- not
    the list, and not the read-only detail page."""
    c, p = ready
    resp = client.post('/sales-orders/create', data=_payload(c, p),
                       follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    so = SalesOrder.query.filter_by(so_number='SO-REDIR-1').one()

    # The form carries NO action attribute -- it posts back to whatever URL it was
    # served from -- so "is this that order's edit form?" has to be asserted from
    # its CONTENT: the editable form is present, prefilled with the number just
    # saved, and in EDIT mode (Update, not Save). All three together cannot be
    # true of the list, of the read-only detail page, or of a blank create form.
    assert re.search(r'<form[^>]*id="soForm"', html), 'no SO form on the landing page'
    field = re.search(r'<input[^>]*id="so_number"[^>]*>', html)
    assert field, 'no so_number input'
    assert 'SO-REDIR-1' in field.group(0), \
        f'the form is not prefilled with the new order: {field.group(0)!r}'
    # the label sits on its own line in the template, so match across whitespace
    assert re.search(r'<button[^>]*id="submitBtn"[^>]*>\s*Update\s*<', html), \
        'the form is not in edit mode (its submit does not read Update)'
    assert so.id                                   # the fixture really created one


def test_the_created_flash_survives_the_redirect(client, db_session, ready):
    """The confirmation is the only signal the save worked, now that the user
    stays on a form that looks much like the one they just submitted."""
    c, p = ready
    resp = client.post('/sales-orders/create', data=_payload(c, p),
                       follow_redirects=True)
    assert 'created successfully' in resp.get_data(as_text=True)


def test_a_refused_create_still_re_renders_the_form_without_redirecting(
        client, db_session, ready):
    """CONTROL: only the SUCCESS path changed."""
    c, p = ready
    client.post('/sales-orders/create', data=_payload(c, p))          # take the number
    resp = client.post('/sales-orders/create', data=_payload(c, p))   # duplicate

    assert resp.status_code == 200, 'a rejected create should not redirect'
    assert 'already exists' in resp.get_data(as_text=True)
    assert SalesOrder.query.filter_by(so_number='SO-REDIR-1').count() == 1


def test_saving_an_edit_still_returns_to_the_detail_page(client, db_session, ready):
    """CONTROL: edit() is untouched -- it lands on the read-only detail page.

    If this ever goes red, someone has applied the create directive to edit too,
    which would leave an editor with no obvious way out of the form.
    """
    c, p = ready
    client.post('/sales-orders/create', data=_payload(c, p), follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-REDIR-1').one()

    data = _payload(c, p)
    data['row_version'] = str(so.row_version)
    resp = client.post(f'/sales-orders/{so.id}/edit', data=data)

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/sales-orders/{so.id}'), \
        resp.headers['Location']
