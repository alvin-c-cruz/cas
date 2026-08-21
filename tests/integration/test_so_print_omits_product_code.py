"""The SO printout names the product, without its internal code.

Owner directive 2026-08-21: "in SO printing, do not include the product's code.
just the product name."

The line cell rendered `CODE - Name`. The code is an internal SKU; the customer
copy should read as the product, not as a warehouse reference.

Scope is the standard printout. print_job_order.html already shows
job_order_name (falling back to name) and never showed the code, and
print_preprinted.html places fields by the layout designer -- neither is touched.
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

#: Deliberately unlike any SO number, customer, date or CSS token on the page, so
#: an absence assertion cannot be satisfied by coincidence elsewhere in the HTML.
CODE = 'ZQX9CODE'
NAME = 'Dried Papaya Chunks'


def _so_with_product(db_session, main_branch):
    c = _customer(db_session)
    p = _product(db_session, code=CODE, name=NAME)
    so = SalesOrder(so_number='SO-PCODE-1', order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('2'), unit_price=Decimal('100.00'),
                                  amount=Decimal('200.00'), line_total=Decimal('200.00')))
    so.total_amount = Decimal('200.00')
    db.session.commit()
    return so


def test_print_shows_the_product_name_without_its_code(client, db_session, admin_user,
                                                       main_branch,
                                                       sales_orders_module_enabled):
    so = _so_with_product(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    # Positive first: without it the absence assertion below passes vacuously
    # whenever the whole line block fails to render.
    assert NAME in html
    assert CODE not in html
    assert f'{CODE} &#8212; {NAME}' not in html      # the old "CODE - Name" cell
    assert f'{CODE} — {NAME}' not in html


def test_the_detail_page_still_shows_the_code(client, db_session, admin_user, main_branch,
                                              sales_orders_module_enabled):
    """CONTROL: only the PRINTOUT drops the code.

    Internal screens still need it to tell two similarly-named products apart --
    this pins the change to the print surface instead of the product display
    everywhere.
    """
    so = _so_with_product(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    html = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)

    assert CODE in html
