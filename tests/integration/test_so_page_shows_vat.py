"""B5 part 1 (Philgen SO-DR trial, 22 Nov 2026): the Sales Order page showed only the VAT-inclusive "Total Sales", so
the VAT had to be worked out by hand (SO 0002: 27,000.00 within 252,000.00). It now shows the Output VAT and the amount
net of VAT under it, worded as on the Sales Invoice page. Work order: 2026-11-22-so-dr-form-minor-polish.md (item 1).
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.sales_orders.models import SalesOrder, SalesOrderItem
from tests.integration._so_helpers import sales_orders_module_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _footer(html):
    foot = re.search(r'<tfoot>(.*?)</tfoot>', html, re.S).group(1)
    rows = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', foot, re.S):
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        rows.append([c for c in cells if c])
    return rows


def _so(main_branch, lines):
    cust = Customer(code='C-V', name='VAT Trading', is_active=True)
    db.session.add(cust); db.session.commit()
    so = SalesOrder(so_number='SO-VAT-1', order_date=date(2026, 11, 23), customer_id=cust.id, customer_name=cust.name,
                    branch_id=main_branch.id, status='confirmed', notes='')
    for n, (amount, vat) in enumerate(lines, 1):
        so.line_items.append(SalesOrderItem(line_number=n, quantity=Decimal('1'), unit_price=Decimal(amount),
                                            amount=Decimal(amount), vat_amount=Decimal(vat),
                                            vat_category='V12' if Decimal(vat) else 'V0'))
    so.calculate_totals()
    db.session.add(so); db.session.commit()
    return so


def _page(client, admin_user, main_branch, so):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id); sess['_fresh'] = True; sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/sales-orders/{so.id}')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_the_page_shows_the_vat_and_the_amount_net_of_vat(client, db_session, admin_user, main_branch,
                                                          sales_orders_module_enabled):
    so = _so(main_branch, [('252000.00', '27000.00')])            # SO 0002 of the trial
    assert _footer(_page(client, admin_user, main_branch, so)) == [
        ['Total Sales', '252,000.00'],
        ['Less: Output VAT', '27,000.00'],
        ['Net of VAT', '225,000.00'],
    ]


def test_several_lines_and_a_vat_free_one_add_up(client, db_session, admin_user, main_branch,
                                                 sales_orders_module_enabled):
    so = _so(main_branch, [('16800.00', '1800.00'), ('3050000.00', '0.00')])
    assert _footer(_page(client, admin_user, main_branch, so)) == [
        ['Total Sales', '3,066,800.00'],
        ['Less: Output VAT', '1,800.00'],
        ['Net of VAT', '3,065,000.00'],
    ]
