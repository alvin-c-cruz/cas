"""The CUSTOMER field follows the same shape as every other header field.

Owner directive 2026-08-31: "The label CUSTOMER and the customer name should
follow the other field's convention, Label left and then value right. But the
height should be twice the other fields. Customer name font size should be 2x
of current."

It used to be TWO full-width rows -- a `colspan=2` CUSTOMER banner above a
`colspan=2` name row -- which is why the old CSS had to suppress the border
between them. It is now one ordinary two-cell row: grey label left, value right,
exactly like SO No. / Order Date / Terms.

The two "2x" numbers are asserted as RATIOS against what they double, not as
bare literals, so the relationship survives a later change to the base sizes:

    row height  42px == 2 x the 21px normal info row
    name size   24px == 2 x the 12px .info-row table font

Measured before the change: normal row 21px, label cell 151.6/361px (42%),
customer name 12px across two 31.5px rows.
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

BASE_FONT_PX = 12          # .info-row table
NORMAL_ROW_PX = 21         # a measured ordinary info row
NAME_FONT_PX = 2 * BASE_FONT_PX
CUSTOMER_ROW_PX = 2 * NORMAL_ROW_PX


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    c = _customer(db_session)
    p = _product(db_session, code='CUST-1', name='Customer Row Widget')
    so = SalesOrder(so_number='SO-CUSTROW-1', order_date=datetime.date(2026, 8, 31),
                    customer_id=c.id, customer_name='HILAS MARKETING CORPORATION',
                    branch_id=main_branch.id, payment_terms='Net 90', status='draft')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return so, client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


def _customer_row(html):
    m = re.search(r'<tr class="customer-row">.*?</tr>', html, re.S)
    assert m, 'no <tr class="customer-row"> -- the row was not converted'
    return m.group(0)


def test_customer_is_a_label_left_value_right_row(printed):
    so, html = printed
    row = _customer_row(html)
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
    assert len(cells) == 2, f'expected 2 cells (label, value), got {len(cells)}'
    assert 'CUSTOMER' in cells[0]
    assert 'HILAS MARKETING CORPORATION' in cells[1]


def test_the_customer_cells_are_not_full_width_banners_any_more(printed):
    """The old shape was two colspan=2 rows. A leftover colspan would put the
    value under the label again while still passing a text-presence check."""
    so, html = printed
    assert 'colspan' not in _customer_row(html)


def test_the_label_cell_uses_the_shared_label_class(printed):
    """It must be the SAME grey label cell as the other fields, not a lookalike
    -- that class is what carries the 42% width and the background."""
    so, html = printed
    first = re.search(r'<td([^>]*)>', _customer_row(html)).group(1)
    assert 'label' in first


def test_the_name_font_is_double_the_table_font(printed):
    so, html = printed
    rule = re.search(r'\.customer-name \{[^}]*\}', html)
    assert rule, '.customer-name rule not found'
    m = re.search(r'font-size:\s*(\d+(?:\.\d+)?)px', rule.group(0))
    assert m, f'.customer-name declares no font-size: {rule.group(0)!r}'
    assert float(m.group(1)) == NAME_FONT_PX

    base = re.search(r'\.info-wide \{[^}]*\}', html)
    bm = re.search(r'font-size:\s*(\d+(?:\.\d+)?)px', base.group(0))
    assert float(m.group(1)) == 2 * float(bm.group(1)), \
        'the name is no longer exactly twice the table font'


def test_the_customer_row_is_double_height(printed):
    so, html = printed
    rule = re.search(r'tr\.customer-row td \{[^}]*\}', html)
    assert rule, 'no height rule for the customer row'
    m = re.search(r'height:\s*(\d+(?:\.\d+)?)px', rule.group(0))
    assert m and float(m.group(1)) == CUSTOMER_ROW_PX

    # the floor must exceed the row's own content, or `height` is inert and the
    # row silently stays whatever the 24px text makes it (the .sig-box lesson)
    content = NAME_FONT_PX * 1.15 + 6 + 2
    assert content < CUSTOMER_ROW_PX, \
        f'content ~{content:.0f}px >= floor {CUSTOMER_ROW_PX}px -- height would be inert'


def test_the_other_fields_are_untouched(printed):
    """CONTROL: only CUSTOMER changed shape."""
    so, html = printed
    for label in ('SO No.', 'Order Date', 'Terms'):
        assert re.search(r'<td class="label">' + re.escape(label) + r'</td>', html), label
    lab = re.search(r'\.info-row td\.label \{[^}]*\}', html)
    assert lab and 'width: 42%' in lab.group(0)


def test_the_customer_row_spans_the_full_block(printed):
    """It lives in its OWN full-width table, not inside the right-hand column.

    Measured reason: the right-hand value cell is 208px and the name needs 409px
    at 24px, so in there it wrapped to three lines and the row rendered ~4x an
    ordinary row instead of the 2x asked for. Full width gives it ~587px, which
    fits on one line and lets the 42px floor decide the height.
    """
    so, html = printed
    body = html[html.index('</style>'):]
    wide = re.search(r'<table class="info-wide">.*?</table>', body, re.S)
    assert wide, 'no full-width info table'
    assert 'customer-row' in wide.group(0)
    assert 'CUSTOMER' in wide.group(0)

    # and it is NOT still inside the two-column block
    cols = re.search(r'<div class="info-row">.*?</div>', body, re.S)
    assert cols and 'customer-row' not in cols.group(0),         'the customer row is still inside the two-column info block'


def test_the_wide_label_column_lines_up_with_the_narrow_ones(printed):
    """20.5% of the full width is the same pixel column as 42% of a half-width
    table, so CUSTOMER's label edge matches SO No.'s below it. If either number
    moves without the other, the two label columns visibly step."""
    so, html = printed
    wide = re.search(r'\.info-wide td\.label \{[^}]*\}', html)
    narrow = re.search(r'\.info-row td\.label \{[^}]*\}', html)
    assert wide and narrow
    w = float(re.search(r'width:\s*([\d.]+)%', wide.group(0)).group(1))
    n = float(re.search(r'width:\s*([\d.]+)%', narrow.group(0)).group(1))
    # half-width table (minus the 16px gap) -> the same absolute column
    assert abs(w - n / 2) < 1.0, f'wide label {w}% is not ~half of narrow {n}%'
