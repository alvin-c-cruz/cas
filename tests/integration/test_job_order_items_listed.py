"""The Job Order Slips page lists each order's line items under the order row.

Owner request 2026-09-12 ("always visible"): what the Job Order Slip PRINT shows per
line -- quantity, description (the product's job-order name, else its name), delivery
date -- nested under each order on the list, in line order. No prices: the page is
operations-facing and unpriced. A closed line stays listed but is marked, so ops does
not produce it.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

UNIT_PRICE = Decimal('4321.99')       # distinctive: must NOT leak into the page


def _login(client, user, branch):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:job_order_slips', '1')
    clear_module_config_cache()
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _so(branch, number, lines):
    """lines: [(product_name, job_order_name, qty, delivery_date, line_status)]"""
    from app.customers.models import Customer
    from app.products.models import Product
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    cust = Customer.query.filter_by(code='JOI').first()
    if cust is None:
        cust = Customer(code='JOI', name='Items Co', is_active=True)
        db.session.add(cust); db.session.commit()
    so = SalesOrder(so_number=number, order_date=date(2026, 9, 1), customer_id=cust.id,
                    customer_name=cust.name, branch_id=branch.id, status='confirmed')
    for n, (pname, joname, qty, ddate, status) in enumerate(lines, start=1):
        p = Product(name=pname, job_order_name=joname, is_active=True)
        db.session.add(p); db.session.commit()
        so.line_items.append(SalesOrderItem(
            line_number=n, product_id=p.id, quantity=Decimal(qty), uom_text='KG',
            unit_price=UNIT_PRICE, amount=Decimal(qty) * UNIT_PRICE,
            delivery_date=ddate, line_status=status))
    db.session.add(so); db.session.commit()
    return so


def _rows_after(html, so_number):
    """The item rows that follow one order's row, up to the next order row."""
    start = html.index(so_number)
    tail = html[start:]
    nxt = re.search(r'<tr class="job-order-row"', tail[1:])
    block = tail[:nxt.start() + 1] if nxt else tail
    return re.findall(r'<tr class="job-order-item[^"]*"[^>]*>(.*?)</tr>', block, re.S)


def test_items_listed_under_their_order_in_line_order(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-IT-1', [
        ('PHILIPPINE DRIED PAPAYA CHUNKS', 'PAPAYA CHUNKS', '6000', date(2026, 9, 20), 'open'),
        ('A ONE DRIED MANGO SLICES 100g', None, '2500', None, 'open'),
    ])
    _so(main_branch, 'SO-IT-2', [('BANANA CHIPS', 'BANANA', '10', None, 'open')])
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    rows = _rows_after(html, 'SO-IT-1')
    assert len(rows) == 2
    assert 'PAPAYA CHUNKS' in rows[0] and '6,000' in rows[0] and '20-Sep-2026' in rows[0]
    assert 'A ONE DRIED MANGO SLICES 100g' in rows[1] and '2,500' in rows[1]   # no job-order name -> product name
    assert 'BANANA' not in ''.join(rows)                                        # the other order's line stays with it
    assert len(_rows_after(html, 'SO-IT-2')) == 1


def test_closed_line_is_marked(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-IT-3', [
        ('X', 'LINE A', '1', None, 'open'),
        ('Y', 'LINE B', '2', None, 'closed'),
    ])
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    rows = _rows_after(html, 'SO-IT-3')
    assert '(closed)' not in rows[0]
    assert '(closed)' in rows[1]
    assert 'class="job-order-item job-order-item--closed"' in html


def test_no_price_leaks(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-IT-4', [('X', 'LINE A', '3', None, 'open')])
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    assert '4,321.99' not in html and '4321.99' not in html
    assert '12,965.97' not in html and '12965.97' not in html      # 3 x unit price


def test_order_without_items_has_no_item_rows(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-IT-5', [])
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    assert 'SO-IT-5' in html
    assert _rows_after(html, 'SO-IT-5') == []
