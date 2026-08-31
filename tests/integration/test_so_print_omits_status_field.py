"""The SO printout carries no Status field in its header block.

Owner directive 2026-08-31, viewing /sales-orders/1/print: "remove the status
field". The header info table showed a labelled `Status | Draft` row. It is a
workflow state, not information the customer copy of an order needs, and on a
draft it printed the word "Draft" on a document being handed out.

SCOPE, and why this test is fussier than a bare `'Status' not in html`:

* the AUDIT FOOTER still reads "SO <number> - Status: <state> | Printed: <ts>".
  That line is provenance for whoever holds the paper, not a header field, and
  the directive named the field. It is asserted PRESENT here so that removing
  the row cannot quietly take the footer with it, and so a later reader can see
  the distinction was deliberate rather than an oversight;
* the detail SCREEN keeps its status badge -- it is a working page;
* "Status" is a substring of nothing else on the page, but the word appears in
  the footer, so a whole-page absence assertion would be wrong in both
  directions. The header table is located and asserted on its own.
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


def _so(db_session, main_branch, status='draft'):
    c = _customer(db_session)
    p = _product(db_session, code='STAT-1', name='Status Widget')
    so = SalesOrder(so_number='SO-STATUS-1', order_date=datetime.date(2026, 8, 31),
                    customer_id=c.id, customer_name='Acme', branch_id=main_branch.id,
                    payment_terms='Net 30', status=status)
    db.session.add(so); db.session.flush()
    db.session.add(SalesOrderItem(sales_order_id=so.id, line_number=1, product_id=p.id,
                                  quantity=Decimal('1'), unit_price=Decimal('10.00'),
                                  amount=Decimal('10.00'), line_total=Decimal('10.00')))
    so.total_amount = Decimal('10.00')
    db.session.commit()
    return so


def _header_labels(html):
    """The `.label` cells of the info block -- the printout's own field names."""
    return [re.sub(r'<[^>]+>', '', m).strip()
            for m in re.findall(r'<td class="label"[^>]*>.*?</td>', html, re.S)]


@pytest.fixture
def printed(client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    so = _so(db_session, main_branch)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    return so, client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)


def test_the_header_block_has_no_status_field(printed):
    so, html = printed
    labels = _header_labels(html)
    assert labels, 'no header labels found -- the assertion below would be vacuous'
    assert 'Status' not in labels
    # the neighbours are still there, so the row was removed rather than the block
    assert 'SO No.' in labels and 'Order Date' in labels and 'Terms' in labels


@pytest.mark.parametrize('status', ['draft', 'confirmed', 'closed', 'cancelled'])
def test_no_status_word_leaks_into_the_header_for_any_state(
        client, db_session, admin_user, main_branch, sales_orders_module_enabled, status):
    """The removed cell rendered `so.status | title`, so each state printed a
    different word. Dropping only the label would leave the VALUE behind on its
    own; every state is checked against the header block specifically."""
    so = _so(db_session, main_branch, status=status)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)

    head = re.search(r'<div class="info-row">.*?</div>', html, re.S)
    assert head, 'info-row block not found'
    assert 'Status' not in head.group(0)
    assert status.title() not in head.group(0)
    assert so.so_number in head.group(0)        # positive control: the block rendered


def test_the_audit_footer_still_records_the_status(printed):
    """CONTROL: only the FIELD went. The footer line is provenance for whoever
    holds the printed sheet, and the directive named the header field."""
    so, html = printed
    foot = re.search(r'<div class="audit-footer">.*?</div>', html, re.S)
    assert foot, 'audit-footer not found'
    assert 'Status:' in foot.group(0)
    assert 'Draft' in foot.group(0)


def test_the_detail_screen_still_shows_the_status_badge(
        client, db_session, admin_user, main_branch, sales_orders_module_enabled):
    """CONTROL: this is a change to the PRINTOUT. The working screen keeps its
    badge -- pinning the change to the print surface, not to status display."""
    so = _so(db_session, main_branch, status='confirmed')
    _login(client, admin_user); _select_branch(client, main_branch.id)
    html = client.get(f'/sales-orders/{so.id}').get_data(as_text=True)
    assert 'Confirmed' in html
