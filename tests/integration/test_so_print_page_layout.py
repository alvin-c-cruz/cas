"""The Sales Order printout's page shape: letter, a fixed 20-line grid, and
signatories anchored to the foot of the page.

Owner directive 2026-08-21: "SO should be letter size portrait. the lines
should be 20 regardless if there are less lines recorded. The signatories
should always be at the very bottom."

Three rules, three separate concerns:

* letter portrait, not A4;
* the line grid always shows 20 rows -- short orders are PADDED with blank
  ruled rows so every printed order has the same body, the way a pre-printed
  pad does. Padding is a MINIMUM, never a cap: an order with more than 20 lines
  must still print all of them;
* the signature block sits at the foot of the sheet regardless of how much of
  the grid is filled.

NOTE ON WHAT THIS TEST CAN SEE: pytest renders HTML, it cannot measure a sheet
of paper. The row counts are real and exact; the bottom-anchoring is asserted
as its MECHANISM (a flex column plus `margin-top: auto`), not as millimetres.
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

GRID_ROWS = 20


def _so_with_lines(db_session, main_branch, n, number='SO-LAYOUT-1'):
    c = _customer(db_session)
    p = _product(db_session, code='LAY-P1', name='Layout Widget')
    so = SalesOrder(so_number=number, order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.flush()
    for i in range(1, n + 1):
        db.session.add(SalesOrderItem(
            sales_order_id=so.id, line_number=i, product_id=p.id,
            quantity=Decimal('1'), unit_price=Decimal('10.00'),
            amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal(10 * n)
    db.session.commit()
    return so


def _print(client, so):
    return client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


def _tbody_rows(html):
    """Every <tr> inside the particulars table's tbody."""
    body = re.search(r'<table class="particulars">.*?<tbody>(.*?)</tbody>', html, re.S)
    assert body, 'particulars tbody not found -- the rest of this test would be vacuous'
    return re.findall(r'<tr[^>]*>.*?</tr>', body.group(1), re.S)


def _media_print_block(html):
    i = html.index('@media print')
    depth, j = 0, html.index('{', i)
    for k in range(j, len(html)):
        if html[k] == '{':
            depth += 1
        elif html[k] == '}':
            depth -= 1
            if depth == 0:
                return html[j:k + 1]
    raise AssertionError('unbalanced @media print block')


# ── paper ────────────────────────────────────────────────────────────────────

def test_page_size_is_letter_portrait(client, db_session, admin_user, main_branch,
                                      sales_orders_module_enabled):
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    block = _media_print_block(_print(client, so))

    m = re.search(r'@page \{[^}]*size:\s*([^;]+);', block)
    assert m is not None, '@page has no size inside @media print'
    assert m.group(1).strip() == 'letter portrait'
    assert 'A4' not in block


# ── the fixed 20-line grid ───────────────────────────────────────────────────

def test_a_short_order_still_prints_twenty_rows(client, db_session, admin_user, main_branch,
                                                sales_orders_module_enabled):
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    assert len(rows) == GRID_ROWS


def test_the_padding_rows_are_blank_not_placeholder_text(client, db_session, admin_user,
                                                         main_branch,
                                                         sales_orders_module_enabled):
    """A filler row is empty ruled space to write on -- not a row of em-dashes.

    The real rows use '—' for a missing UOM/date, so a filler row built from the
    same markup would print 18 rows of dashes.
    """
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    fillers = [r for r in rows if 'so-filler' in r]
    assert len(fillers) == GRID_ROWS - 2

    joined = ''.join(fillers)
    assert '—' not in joined
    assert 'Layout Widget' not in joined
    assert not re.search(r'\d', joined), 'a filler row carries a number'


def test_twenty_rows_exactly_when_the_order_has_twenty_lines(client, db_session, admin_user,
                                                             main_branch,
                                                             sales_orders_module_enabled):
    """CONTROL: at exactly 20 real lines nothing is padded."""
    so = _so_with_lines(db_session, main_branch, GRID_ROWS, number='SO-LAYOUT-20')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    assert len(rows) == GRID_ROWS
    assert not [r for r in rows if 'so-filler' in r]


def test_a_long_order_is_not_truncated_to_twenty(client, db_session, admin_user, main_branch,
                                                 sales_orders_module_enabled):
    """20 is a MINIMUM, not a cap.

    Mutation target: implement the grid by slicing the line items to 20 and this
    goes RED -- silently dropping billed lines off a printed order is far worse
    than a short page.
    """
    so = _so_with_lines(db_session, main_branch, 23, number='SO-LAYOUT-23')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    assert len(rows) == 23
    assert not [r for r in rows if 'so-filler' in r]


# ── signatories at the foot ──────────────────────────────────────────────────

def test_signatories_are_anchored_to_the_bottom_of_the_page(client, db_session, admin_user,
                                                            main_branch,
                                                            sales_orders_module_enabled):
    """Mechanism: the sheet is a flex column and the signature block takes the
    slack via `margin-top: auto`.

    Both halves are asserted. `margin-top: auto` in a non-flex container does
    nothing at all, so the flex declaration is what makes it real.
    """
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _print(client, so)

    # Look OUTSIDE @media print: that block carries its own `.page-wrap` rule and
    # it is declared first, so a naive search finds the print override instead of
    # the base rule the flex column actually lives in.
    outside = html.replace(_media_print_block(html), '')
    wrap = re.search(r'\.page-wrap \{[^}]*\}', outside)
    assert wrap, '.page-wrap base rule not found outside @media print'
    assert 'flex-direction: column' in wrap.group(0)
    assert 'display: flex' in wrap.group(0)

    bottom = re.search(r'\.page-bottom \{[^}]*\}', html)
    assert bottom, '.page-bottom rule not found'
    assert re.search(r'margin-top:\s*auto', bottom.group(0))

    # the signature row must actually live inside that bottom block
    blk = re.search(r'<div class="page-bottom">(.*?)</div>\s*</div>\s*</body>', html, re.S)
    assert blk and 'sig-row' in blk.group(1), \
        'the signature row is not inside .page-bottom -- the anchor applies to nothing'
