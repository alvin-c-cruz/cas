"""The Sales Order printout's three signatory captions.

Owner directive 2026-08-21: the SO's signatories are Prepared By / Noted By /
Approved By -- the same trio the Purchase Requisition already prints. Before
this, the SO printed PREPARED BY / APPROVED BY / RECEIVED BY, which both named
a role the owner does not use (RECEIVED BY) and put Approved in the middle slot.

These are blank ruled lines signed by hand: the SO has no signatory COLUMNS and
no company setting, unlike PR/RR/PO. So this is purely what the printout says,
and the test asserts the captions IN ORDER -- a presence-only assertion would
still pass if two captions swapped slots, which is exactly the defect being
fixed.
"""
import datetime
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

EXPECTED_ROLES = ['PREPARED BY', 'NOTED BY', 'APPROVED BY']
RETIRED_ROLE = 'RECEIVED BY'


def _so_with_a_line(db_session, main_branch, number):
    c = _customer(db_session)
    p = _product(db_session, code='SIG-P1', name='Signatory Widget')
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(
        sales_order_id=so.id, line_number=1, product_id=p.id,
        quantity=Decimal('2'), unit_price=Decimal('100.00'),
        amount=Decimal('200.00'), line_total=Decimal('200.00')))
    so.total_amount = Decimal('200.00')
    db.session.commit()
    return so


def _sig_titles(html):
    """The .sig-title captions, in the order the printout renders them."""
    import re
    return re.findall(r'<div class="sig-title">([^<]+)</div>', html)


def test_so_print_signatory_captions_are_prepared_noted_approved(
        client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    so = _so_with_a_line(db_session, main_branch, 'SO-2026-06-SIG1')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(f'/sales-orders/{so.id}/print')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Order matters -- this is the assertion a caption swap cannot survive.
    assert _sig_titles(html) == EXPECTED_ROLES


def test_so_print_no_longer_names_received_by(
        client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    """The retired caption is gone from the rendered page.

    Paired with the positive test above per the project's absence-test rule: an
    absence assertion alone passes vacuously if the whole block fails to render.
    """
    so = _so_with_a_line(db_session, main_branch, 'SO-2026-06-SIG2')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    assert RETIRED_ROLE not in html
    assert len(_sig_titles(html)) == 3      # the block DID render -- not a vacuous pass
