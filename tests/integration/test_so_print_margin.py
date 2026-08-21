"""The Sales Order printout's page margin.

Owner directive 2026-08-21: "make it 5mm" (was 15mm).

TWO rules together decide how far in the content actually starts, which is why
both are asserted here. `@page { margin }` sets the paper margin, but
`.page-wrap { padding: 24px }` sits OUTSIDE `@media print`, so it printed as
well -- 15mm + 24px was an effective ~21.3mm inset. Changing only the @page
number would have left ~11.3mm on paper while the stylesheet claimed 5mm.

The screen keeps its 24px breathing room; only the printed page is flush to
5mm.

NOTE ON WHAT THIS TEST CAN SEE: pytest cannot measure a printed page. It
asserts the two CSS rules that produce the margin, in the rendered response --
which is the mechanism, not the millimetres on paper.
"""
import datetime
import pytest
import re
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch, _customer,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _so(db_session, main_branch):
    c = _customer(db_session)
    so = SalesOrder(so_number='SO-MARGIN-1', order_date=datetime.date(2026, 6, 15),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    status='draft')
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


def _print_html(client, db_session, admin_user, main_branch):
    so = _so(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


def _media_print_block(html):
    """Just the @media print { ... } body, so a rule outside it cannot satisfy
    an assertion meant for the print stylesheet."""
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


def test_page_margin_is_5mm(client, db_session, admin_user, main_branch,
                            sales_orders_module_enabled):
    html = _print_html(client, db_session, admin_user, main_branch)
    block = _media_print_block(html)

    m = re.search(r'@page \{[^}]*margin:\s*([0-9.]+mm)', block)
    assert m is not None, '@page has no margin inside @media print'
    assert m.group(1) == '5mm'


def test_the_wrapper_padding_does_not_add_to_the_printed_margin(client, db_session, admin_user,
                                                                main_branch,
                                                                sales_orders_module_enabled):
    """The load-bearing half: 24px of wrapper padding used to print too.

    Mutation target: delete the print-time `.page-wrap { padding: 0 }` and this
    goes RED while the @page test above stays green -- which is exactly the
    false-confidence state the directive was given in.
    """
    html = _print_html(client, db_session, admin_user, main_branch)
    block = _media_print_block(html)

    assert re.search(r'\.page-wrap\s*\{[^}]*padding:\s*0', block), \
        'wrapper padding is not neutralised for print -- the real margin exceeds 5mm'

    # ...and it must WIN the cascade. `.page-wrap { padding: 24px }` is declared
    # LATER in the same stylesheet at equal specificity, and @media adds none, so
    # a plain `padding: 0` inside the print block loses -- while the file still
    # reads as though the printed margin were 5mm.
    print_rule = re.search(r'\.page-wrap\s*\{[^}]*padding:\s*0[^}]*\}', block).group(0)
    screen_rule_comes_later = html.index('padding: 24px') > html.index(print_rule)
    assert ('!important' in print_rule) or not screen_rule_comes_later, \
        'the print-time padding:0 is overridden by the later .page-wrap rule'


def test_screen_keeps_its_breathing_room(client, db_session, admin_user, main_branch,
                                         sales_orders_module_enabled):
    """CONTROL: only the PRINTED page goes flush; the on-screen preview keeps 24px.

    Without this, zeroing the padding globally would also pass the test above.
    """
    html = _print_html(client, db_session, admin_user, main_branch)
    block = _media_print_block(html)
    outside = html.replace(block, '')

    assert re.search(r'\.page-wrap \{[^}]*padding:\s*24px', outside), \
        'the screen rule lost its 24px padding'
