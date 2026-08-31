"""The SO printout carries six line columns, and gives the width to the product.

Owner directive 2026-08-31, from a live PhilGen order: the product name
"DRIED PAPAYA CHUNKS (RED LADY PAPAYA VARIETY) (LOW SUGAR, LOW SO2 200ppm)"
wrapped to FOUR lines while VT, Delivery Date and Delivery Site sat beside it
holding "V0 (0.00%)", a wrapped date, and an em dash. The Product column had
22% of the table while those three took 31% between them. Drop them; Product
takes the reclaimed width.

Absence is asserted on the `<th>` cells, not on the bare words. "VT" appears in
`vat_category`/CSS tokens and "Delivery" in the header block's "Expected
Delivery" row, so a naive `'VT' not in html` would fail for reasons that have
nothing to do with the line table (memory `html-comment-leaks-to-response`).

The cell counts matter as much as the headers: a `<tr>` in the 20-row filler grid
or the totals row that still emits nine cells silently widens the table past its
own header set, which no header assertion would catch.
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

KEPT = ['#', 'Product', 'Qty', 'UOM', 'Unit Price', 'Amount']
DROPPED = ['VT', 'Delivery Date', 'Delivery Site']

#: As long as the name that triggered this, so the fix is exercised against the
#: real shape rather than a short placeholder.
LONG_NAME = 'DRIED PAPAYA CHUNKS (RED LADY PAPAYA VARIETY) (LOW SUGAR, LOW SO2 200ppm)'


def _so(db_session, main_branch, name=LONG_NAME):
    c = _customer(db_session)
    p = _product(db_session, code='PAPAYA1', name=name)
    so = SalesOrder(so_number='SO-COLS-1', order_date=datetime.date(2026, 8, 31),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    expected_delivery_date=datetime.date(2026, 9, 19),
                    status='draft')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('6000'), unit_price=Decimal('500.00'),
                                  amount=Decimal('3000000.00'),
                                  line_total=Decimal('3000000.00')))
    so.total_amount = Decimal('3000000.00')
    db.session.commit()
    return so


def _particulars(html):
    """The line table only -- the header block above it is a table too."""
    m = re.search(r'<table class="particulars".*?</table>', html, re.S)
    assert m, 'the particulars table did not render'
    return m.group(0)


def _headers(table_html):
    return [re.sub(r'<[^>]+>', '', h).strip()
            for h in re.findall(r'<th[^>]*>.*?</th>', table_html, re.S)]


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    so = _so(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)
    return so, html


def test_the_line_table_carries_exactly_the_six_kept_columns(printed):
    so, html = printed
    headers = _headers(_particulars(html))
    assert headers == KEPT


@pytest.mark.parametrize('dropped', DROPPED)
def test_a_dropped_column_has_no_header(printed, dropped):
    so, html = printed
    assert dropped not in _headers(_particulars(html))


def test_the_product_name_still_prints_in_full(printed):
    # The positive control for every absence above, and the point of the change:
    # widening the column must not have come at the cost of truncating the name.
    so, html = printed
    assert LONG_NAME in html


def test_expected_delivery_survives_in_the_header_block(printed):
    """CONTROL: only the LINE column went away.

    'Delivery Date' as a line column and 'Expected Delivery' in the order header
    are different fields. Dropping the column must not touch the header row --
    and this is exactly why the absence assertions above are scoped to the
    particulars table instead of the whole page.
    """
    so, html = printed
    assert 'Expected Delivery' in html


def test_every_body_row_has_six_cells(printed):
    """The filler grid included. A row still emitting nine <td> widens the table
    past its own header set -- invisible to a header-only assertion."""
    so, html = printed
    table = _particulars(html)
    body = re.search(r'<tbody.*?</tbody>', table, re.S).group(0)
    rows = re.findall(r'<tr[^>]*>.*?</tr>', body, re.S)
    assert rows, 'no body rows rendered'
    counts = {len(re.findall(r'<td', r)) for r in rows}
    assert counts == {6}, f'body rows have varying cell counts: {sorted(counts)}'


def test_the_totals_row_spans_the_six_columns(printed):
    """`Total Sales` labels columns 1-5 and the figure sits under Amount, so the
    row must account for exactly six columns -- no leftover trailing cells from
    the nine-column layout."""
    so, html = printed
    foot = re.search(r'<tfoot.*?</tfoot>', _particulars(html), re.S).group(0)
    cells = re.findall(r'<td[^>]*>', foot)
    spans = sum(int(re.search(r'colspan="(\d+)"', c).group(1)) if 'colspan' in c else 1
                for c in cells)
    assert spans == 6, f'totals row spans {spans} columns, expected 6'

# --- header + cell presentation (owner, 2026-08-31) -------------------------

def test_the_column_headers_are_centered(printed):
    """"column headers should be centered". Two halves: the rule must say
    center, AND no header may carry an inline text-align overriding it -- Qty,
    Unit Price and Amount each used to declare text-align:right inline, which
    wins over the stylesheet."""
    so, html = printed
    rule = re.search(r'\.particulars th \{[^}]*\}', html)
    assert rule, '.particulars th rule not found'
    assert re.search(r'text-align:\s*center', rule.group(0))

    heads = re.findall(r'<th[^>]*>', _particulars(html))
    assert heads, 'no header cells rendered'
    overrides = [h for h in heads if 'text-align' in h]
    assert not overrides, f'inline alignment overrides the centered rule: {overrides}'


def test_the_column_header_text_is_black_not_white(printed):
    """"the column header font is gray, change it to Black".

    The rule was white on a near-black band. Browsers DROP background colours
    when printing unless print-color-adjust forces them, so on paper the band
    disappeared and white text landed on white. Black text is legible whether or
    not the background survives -- so this asserts the colour is dark AND that
    the background is not the old near-black (which would hide black text).
    """
    so, html = printed
    rule = re.search(r'\.particulars th \{[^}]*\}', html)
    body = rule.group(0)
    colour = re.search(r'(?<!-)color:\s*(#[0-9a-fA-F]{3,6})', body)
    assert colour, f'no text colour on the header rule: {body!r}'
    assert colour.group(1).lower() in ('#111', '#000'), colour.group(1)
    bg = re.search(r'background:\s*(#[0-9a-fA-F]{3,6})', body)
    assert bg and bg.group(1).lower() not in ('#222', '#111', '#000'),         'a dark band would hide the now-black header text'


def test_the_uom_cells_are_centered(printed):
    """"the line items' UOM should be centered." The cell must carry the class
    AND the class must actually centre -- a class with no rule is inert."""
    so, html = printed
    table = _particulars(html)
    assert re.search(r'<td class="uom"', table), 'no UOM cell carries the class'
    rule = re.search(r'\.particulars td\.uom \{[^}]*\}', html)
    assert rule, '.particulars td.uom rule not found'
    assert re.search(r'text-align:\s*center', rule.group(0))


def test_the_amount_cells_are_still_right_aligned(printed):
    """CONTROL: centering headers and the UOM column must not disturb the
    numeric BODY cells -- figures stay right-aligned and monospaced."""
    so, html = printed
    rule = re.search(r'\.particulars td\.amount \{[^}]*\}', html)
    assert rule, '.particulars td.amount rule not found'
    assert re.search(r'text-align:\s*right', rule.group(0))
    assert 'monospace' in rule.group(0)
    assert re.search(r'<td class="amount"', _particulars(html))
