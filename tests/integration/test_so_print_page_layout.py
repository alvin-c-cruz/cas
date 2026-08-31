"""The Sales Order printout's page shape: letter, a fixed 10-line grid, and
signatories anchored to the foot of the page.

Owner directive 2026-08-21: "SO should be letter size portrait. the lines
should be 20 regardless if there are less lines recorded. The signatories
should always be at the very bottom."

Owner directive 2026-08-31 SUPERSEDES the row count: "cut the number of line
items into half. Increase the height of the surviving line items." So the grid
is 10 rows at double height. GRID_ROWS * ROW_HEIGHT_PX is deliberately unchanged
(10 x 51 == 20 x 25.5 == 510px), which keeps the signature block and page foot
exactly where they were -- the rows got roomier, the sheet did not change shape.

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

GRID_ROWS = 10
ROW_HEIGHT_PX = 51           # was 25.5 across 20 rows
GRID_TOTAL_PX = 510          # GRID_ROWS * ROW_HEIGHT_PX -- unchanged by the halving


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


# ── the fixed 10-line grid, at double row height ─────────────────────────────

def test_a_short_order_still_prints_ten_rows(client, db_session, admin_user, main_branch,
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


def test_ten_rows_exactly_when_the_order_has_ten_lines(client, db_session, admin_user,
                                                             main_branch,
                                                             sales_orders_module_enabled):
    """CONTROL: at exactly 10 real lines nothing is padded."""
    so = _so_with_lines(db_session, main_branch, GRID_ROWS, number='SO-LAYOUT-10')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    assert len(rows) == GRID_ROWS
    assert not [r for r in rows if 'so-filler' in r]


def test_a_long_order_is_not_truncated_to_ten(client, db_session, admin_user, main_branch,
                                                 sales_orders_module_enabled):
    """10 is a MINIMUM, not a cap.

    Mutation target: implement the grid by slicing the line items to 10 and this
    goes RED -- silently dropping billed lines off a printed order is far worse
    than a short page. Halving the grid doubles the stakes here: an order of 12
    lines used to fit inside the padding and now exceeds it.
    """
    so = _so_with_lines(db_session, main_branch, 23, number='SO-LAYOUT-23')
    _login(client, admin_user); _select_branch(client, main_branch.id)

    rows = _tbody_rows(_print(client, so))
    assert len(rows) == 23
    assert not [r for r in rows if 'so-filler' in r]



def test_every_grid_row_carries_the_doubled_height(client, db_session, admin_user, main_branch,
                                                   sales_orders_module_enabled):
    """The rule applies to EVERY tbody cell -- data rows and filler alike.

    Halving the grid without raising the height would leave the body occupying
    half the sheet and the signature block floating up to meet it; raising the
    height without halving would overflow onto a second page. The two numbers
    only make sense together, which is what the next test pins.
    """
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _print(client, so)

    rule = re.search(r'table\.particulars tbody td \{[^}]*\}', html)
    assert rule, 'no height rule for particulars tbody cells'
    m = re.search(r'height:\s*([\d.]+)px', rule.group(0))
    assert m, f'the rule sets no px height: {rule.group(0)!r}'
    assert float(m.group(1)) == ROW_HEIGHT_PX


def test_the_grid_still_occupies_the_same_total_height(client, db_session, admin_user,
                                                       main_branch,
                                                       sales_orders_module_enabled):
    """rows x height is the invariant the page shape actually depends on.

    This is the test that fails if someone later changes ONE of the two numbers:
    the sheet is letter, the signature block is anchored to its foot, and the
    body between them was 510px before the halving and must stay 510px after.
    """
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _print(client, so)

    rows = _tbody_rows(html)
    rule = re.search(r'table\.particulars tbody td \{[^}]*\}', html)
    height = float(re.search(r'height:\s*([\d.]+)px', rule.group(0)).group(1))

    assert len(rows) * height == GRID_TOTAL_PX
    assert GRID_ROWS * ROW_HEIGHT_PX == GRID_TOTAL_PX      # the constants agree too



# ── the signature block's own height ─────────────────────────────────────────

SIG_BOX_PX = 124             # doubled from the 62px it actually rendered at
SIG_GAP_PX = 86              # .sig-title margin-bottom -- where the signing space lives


def test_the_signature_boxes_are_double_height(client, db_session, admin_user, main_branch,
                                               sales_orders_module_enabled):
    """Owner directive 2026-08-31: double the height of the signatory footer.

    The height is pinned in TWO places that must agree, and the test asserts the
    arithmetic between them rather than each number in isolation:

        5 pad + 12 title + 86 gap + 14 name + 5 pad + 2 borders == 124

    That matters because the previous `min-height: 56px` was INERT -- the content
    already came to 62px, so the floor was never reached and raising it alone
    would have added dead space BELOW the signature line instead of above it.
    Growing the gap is what puts the room where a person actually signs.
    """
    so = _so_with_lines(db_session, main_branch, 2)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = _print(client, so)

    box = re.search(r'\.sig-box \{[^}]*\}', html)
    assert box, '.sig-box rule not found'
    m = re.search(r'min-height:\s*(\d+)px', box.group(0))
    assert m and int(m.group(1)) == SIG_BOX_PX

    title = re.search(r'\.sig-box \.sig-title \{[^}]*\}', html)
    assert title, '.sig-title rule not found'
    g = re.search(r'margin-bottom:\s*(\d+)px', title.group(0))
    assert g and int(g.group(1)) == SIG_GAP_PX

    pad = re.search(r'padding:\s*(\d+)px', box.group(0))
    assert pad, '.sig-box has no padding declaration'
    content = 2 * int(pad.group(1)) + 12 + SIG_GAP_PX + 14 + 2
    assert content == SIG_BOX_PX, (
        f'the floor ({SIG_BOX_PX}px) and the content ({content}px) disagree -- '
        'min-height is inert again, so the box height is not what this test claims')


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
