"""Which header column each field sits in, and in what order.

Owner directive 2026-08-31: "interchange the positions of SO No. and Order Date,
with PO No. and PO Date."

So the two pairs trade columns:

    LEFT   PO No. / PO Date  ...then Expected Delivery, Terms, Reference
    RIGHT  TIN, Address...   then SO No. / Order Date

WHY ORDER IS ASSERTED, NOT JUST MEMBERSHIP: every one of these rows except
Terms, SO No. and Order Date is wrapped in an `{% if %}`, so a field can vanish
from a rendered page for reasons that have nothing to do with placement. A test
that only asked "is PO No. in the left table" would pass on a page where the
whole pair is absent. The fixture therefore populates EVERY optional field, and
the assertion is the exact label sequence per column.

A side effect worth naming: SO No. and Order Date are the only unconditional
fields here, and they are now both on the RIGHT. The right column used to render
completely empty for a customer with no TIN, address or PO (visible in the
2026-08-31 screenshots); it can no longer be empty. The LEFT column can now be
sparse instead -- Terms alone, if there is no PO, no expected delivery and no
reference -- which the last test below pins deliberately.
"""
import datetime
import re

import pytest
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer, _product,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

LEFT_ORDER = ['PO No.', 'PO Date', 'Expected Delivery', 'Terms', 'Reference']
RIGHT_ORDER = ['TIN', 'Address', 'SO No.', 'Order Date']


def _so(db_session, main_branch, full=True):
    c = _customer(db_session)
    p = _product(db_session, code='PLACE-1', name='Placement Widget')
    so = SalesOrder(so_number='SO-PLACE-1', order_date=datetime.date(2026, 8, 31),
                    customer_id=c.id, customer_name='HILAS MARKETING CORPORATION',
                    branch_id=main_branch.id, payment_terms='Net 90', status='draft')
    if full:
        so.expected_delivery_date = datetime.date(2026, 9, 19)
        so.reference = 'REF-42'
        so.customer_tin = '000-000-000-000'
        so.customer_address = 'Sitio Lamcanal, Malungon'
        so.customer_po_number = '16642'
        so.customer_po_date = datetime.date(2026, 8, 28)
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


def _columns(html):
    """(left_labels, right_labels) from the two-column info block."""
    block = re.search(r'<div class="info-row">(.*?)\n  </div>', html, re.S)
    assert block, 'info-row block not found'
    tables = re.findall(r'<table>(.*?)</table>', block.group(1), re.S)
    assert len(tables) == 2, f'expected 2 info tables, found {len(tables)}'
    return [re.findall(r'<td class="label">([^<]+)</td>', t) for t in tables]


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    so = _so(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return so, client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


def test_the_left_column_leads_with_the_customer_po(printed):
    so, html = printed
    left, _ = _columns(html)
    assert left == LEFT_ORDER


def test_the_right_column_ends_with_the_so_number_and_date(printed):
    so, html = printed
    _, right = _columns(html)
    assert right == RIGHT_ORDER


def test_the_values_travelled_with_their_labels(printed):
    """Moving a <tr> can leave the label and value out of step -- assert each
    pair, not just that both strings are somewhere on the page."""
    so, html = printed
    for label, value in (('PO No.', '16642'),
                         ('PO Date', '28 August 2026'),
                         ('SO No.', 'SO-PLACE-1'),
                         ('Order Date', '31 August 2026')):
        pat = (r'<td class="label">' + re.escape(label) +
               r'</td>\s*<td>(?:<strong>)?' + re.escape(value))
        assert re.search(pat, html), f'{label} is not paired with {value!r}'


def test_the_right_column_can_no_longer_render_empty(client, db_session, admin_user,
                                                     main_branch,
                                                     sales_orders_module_enabled):
    """A customer with no TIN, address or PO used to leave the right column
    completely blank. SO No. and Order Date are unconditional, so it cannot be
    empty any more -- and the LEFT column is the sparse one instead."""
    so = _so(db_session, main_branch, full=False)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    left, right = _columns(client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True))

    assert right == ['SO No.', 'Order Date']
    assert left == ['Terms']
