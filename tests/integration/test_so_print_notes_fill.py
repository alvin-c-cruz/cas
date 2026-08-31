"""The SO printout's Notes box fills the gap above the signatories.

Owner directive 2026-08-21: "Notes' box should fill the space between after the
line items and before signatories."

Since the sheet became a flex column (761c8b31) the slack between the 20-row
grid and the foot-anchored signature block was empty space. The Notes box now
takes it: `flex: 1` inside that column, so it stretches from the bottom of the
grid down to the signature block instead of hugging its own text.

Two structural facts have to hold together, so both are asserted:
  * the box declares flex-grow, and
  * it is a DIRECT child of .page-wrap, ahead of .page-bottom -- flex-grow on a
    node whose parent is not the flex column does nothing at all.

NOTE ON WHAT THIS TEST CAN SEE: pytest cannot measure the rendered box. It
asserts the mechanism and the DOM position that produce the stretch.
"""
import datetime
import pytest
import re
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

NOTE = 'THIS IS A SAMPLE SALES ORDER'


def _so(db_session, main_branch, notes, number):
    c = _customer(db_session)
    p = _product(db_session, code='NF-P1', name='Notes Widget')
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft', notes=notes)
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


def test_notes_box_grows_to_fill_the_gap(client, db_session, admin_user, main_branch,
                                         sales_orders_module_enabled):
    so = _so(db_session, main_branch, NOTE, 'SO-NOTESFILL-1')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    rule = re.search(r'\.notes-box \{[^}]*\}', html)
    assert rule, '.notes-box rule not found'
    assert re.search(r'flex:\s*1|flex-grow:\s*1', rule.group(0)), \
        'the notes box does not grow -- the gap above the signatories stays empty'


def test_notes_box_is_a_direct_child_of_the_flex_column(client, db_session, admin_user,
                                                        main_branch,
                                                        sales_orders_module_enabled):
    """flex-grow only does something if the PARENT is the flex column.

    Mutation target: nest the box in a plain wrapper div and this goes RED while
    the CSS assertion above stays green -- the exact shape of a change that
    reads as done and renders unchanged.
    """
    so = _so(db_session, main_branch, NOTE, 'SO-NOTESFILL-2')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    body = html[html.index('<div class="page-wrap">'):]
    # the grid closes, then the notes box, then the foot block -- nothing between.
    # Anchor on the PARTICULARS table specifically: `the first </table>` used to
    # mean the same thing only because the info block was the sheet's first table.
    # A full-width CUSTOMER table was added above it on 2026-08-31, which moved
    # that anchor and made this read a slice starting two tables too early.
    grid = body.index('<table class="particulars">')
    tail = body[grid:]
    tail = tail[tail.index('</table>'):]
    tail = tail[:tail.index('<div class="page-bottom">')]
    assert 'notes-box' in tail, 'the notes box is not between the grid and the foot block'
    assert tail.count('<div') == tail.count('notes-box'), \
        'an extra wrapper sits between .page-wrap and the notes box, killing flex-grow'


def test_an_order_without_notes_renders_no_box(client, db_session, admin_user, main_branch,
                                               sales_orders_module_enabled):
    """CONTROL: the box is still conditional.

    Filling the gap must not turn an empty Notes box into permanent furniture on
    every order that has nothing to say.
    """
    so = _so(db_session, main_branch, '', 'SO-NOTESFILL-3')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    assert 'notes-box' not in html.split('<style>')[-1].split('</style>')[-1], \
        'an empty order still renders the Notes box'
