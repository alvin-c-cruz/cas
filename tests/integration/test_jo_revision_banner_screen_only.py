"""The Job Order Slip's revision banners are screen-only.

Owner directive 2026-08-21: "the red boxes should not be included" -- "in
printing".

The slip prints THREE copies of the same job order per sheet (`jo_copy()` is
called three times), so an amended order rendered three red "REV. n --
destroy prior copies" banners, one per copy. That is why the report said
boxes, plural. They still show on screen, where they warn whoever is about to
press Print; they are suppressed in the print stylesheet.

This mirrors the treatment the SO's own printout got in bb50cf67. It was left
out of that commit deliberately -- the slip goes to the production floor, where
"destroy prior copies" on paper is arguably wanted -- and the owner has now
decided otherwise.

NOTE ON WHAT THIS TEST CAN SEE: pytest cannot drive a printer. It asserts the
mechanism (the class on every banner, and the @media print rule that hides that
class), not the ink.
"""
import datetime
import pytest
import re
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

COPIES_PER_SHEET = 3


def _amended_so(db_session, main_branch, number, revision_number=1):
    c = _customer(db_session)
    p = _product(db_session, code='JOB-P1', name='Job Widget')
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='confirmed')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('5'), unit_price=Decimal('10.00'),
                                  amount=Decimal('50.00'), line_total=Decimal('50.00')))
    so.total_amount = Decimal('50.00')
    for n in range(revision_number + 1):
        db.session.add(SalesOrderRevision(sales_order_id=so.id, revision_number=n,
                                          snapshot_json='{}'))
    db.session.commit()
    return so


def _slip(client, so):
    return client.get(f'/sales-orders/{so.so_number}/print-job-order').get_data(as_text=True)


def _banner_classes(html):
    return re.findall(r'<div class="([^"]*print-rev-banner[^"]*)"', html)


def test_every_copy_marks_its_banner_screen_only(client, db_session, admin_user, main_branch,
                                                 sales_orders_module_enabled):
    """All three copies, not just the first.

    The banner lives inside the jo_copy() macro, so one missed edit would leave
    every copy printing it -- but an assertion on only the FIRST banner would
    pass even then.
    """
    so = _amended_so(db_session, main_branch, 'SO-JOBAN-1')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    classes = _banner_classes(_slip(client, so))
    assert len(classes) == COPIES_PER_SHEET, \
        f'expected {COPIES_PER_SHEET} banners (one per copy), got {len(classes)}'
    for c in classes:
        assert 'screen-only' in c.split()


def test_the_class_actually_suppresses_printing(client, db_session, admin_user, main_branch,
                                                sales_orders_module_enabled):
    """The other half: a class with no rule hides nothing."""
    so = _amended_so(db_session, main_branch, 'SO-JOBAN-2')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _slip(client, so)

    print_block = html[html.index('@media print'):]
    assert '.screen-only { display: none !important; }' in print_block[:400]


def test_banners_still_render_on_screen(client, db_session, admin_user, main_branch,
                                        sales_orders_module_enabled):
    """CONTROL: screen-only means hidden ON PAPER, not deleted."""
    so = _amended_so(db_session, main_branch, 'SO-JOBAN-3')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _slip(client, so)

    assert 'REV. 1' in html
    assert 'destroy prior copies' in html


def test_an_unamended_order_has_no_banner(client, db_session, admin_user, main_branch,
                                          sales_orders_module_enabled):
    """CONTROL: Rev 0 is the order as originally confirmed -- nothing supersedes it."""
    so = _amended_so(db_session, main_branch, 'SO-JOBAN-4', revision_number=0)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _slip(client, so)

    assert _banner_classes(html) == []
    assert 'destroy prior copies' not in html
