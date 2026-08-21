"""The amended-SO revision banner is screen-only -- it must not go on paper.

Owner directive 2026-08-21: "the red box in amended SO should not be printable."

The banner ("REV. 1 -- Supersedes Rev. 0 ... destroy prior copies") still renders
on screen, where it warns whoever is about to press Print, but it is suppressed
in the print stylesheet so it never reaches the printed document.

NOTE ON WHAT THIS TEST CAN SEE: pytest renders HTML, it cannot drive a printer,
so this asserts the MECHANISM -- the banner carries the file's own `screen-only`
class, and that class is hidden inside `@media print`. Both halves are asserted,
because either one alone is worthless: the class with no rule hides nothing, and
the rule with no class applies to nothing.
"""
import datetime
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _amended_so(db_session, main_branch, revision_number=1):
    c = _customer(db_session)
    so = SalesOrder(so_number='SO-REVBAN-1', order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='confirmed')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    for n in range(revision_number + 1):
        db.session.add(SalesOrderRevision(sales_order_id=so.id, revision_number=n,
                                          snapshot_json='{}'))
    db.session.commit()
    return so


def _banner_tag(html):
    import re
    m = re.search(r'<div class="([^"]*print-rev-banner[^"]*)"', html)
    return m.group(1) if m else None


def test_revision_banner_is_marked_screen_only(client, db_session, admin_user, main_branch,
                                               sales_orders_module_enabled):
    so = _amended_so(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    classes = _banner_tag(html)
    assert classes is not None, 'the banner did not render at all -- test would be vacuous'
    assert 'screen-only' in classes.split()

    # ...and the class actually suppresses printing. Without this half, someone
    # could delete the @media print rule and the assertion above stays green.
    print_block = html[html.index('@media print'):]
    assert '.screen-only { display: none !important; }' in print_block[:400]


def test_banner_still_renders_on_screen_for_an_amended_order(client, db_session, admin_user,
                                                             main_branch,
                                                             sales_orders_module_enabled):
    """CONTROL: screen-only means hidden ON PAPER, not deleted.

    The warning is still what tells the person at the screen that this copy
    supersedes an earlier one.
    """
    so = _amended_so(db_session, main_branch, revision_number=1)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    assert 'REV. 1' in html
    assert 'destroy prior copies' in html


def test_unamended_order_has_no_banner_at_all(client, db_session, admin_user, main_branch,
                                              sales_orders_module_enabled):
    """CONTROL: Rev 0 is the order as originally confirmed -- nothing supersedes it."""
    so = _amended_so(db_session, main_branch, revision_number=0)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    assert _banner_tag(html) is None
    assert 'destroy prior copies' not in html
