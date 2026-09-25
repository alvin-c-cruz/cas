"""The SO number reads in red on the list, the detail page, the entry form and both printouts.

Owner, 2026-09-25: "the SO# should be red font" -- chosen for all four surfaces. Each assertion
is on the ELEMENT that carries the number, never on a bare class name, because inline <style>
text in the page would satisfy a class-name substring even if no element used it.
"""
import datetime
import re

import pytest

from app import db
from app.sales_orders.models import SalesOrder
from app.settings import AppSettings
from tests.integration._so_helpers import (sales_orders_module_enabled, _login,  # noqa: F401
                                           _select_branch, _customer)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

SO_NO = '00009E'


@pytest.fixture
def so(db_session, main_branch):
    c = _customer(db_session)
    o = SalesOrder(so_number=SO_NO, order_date=datetime.date(2026, 9, 25), customer_id=c.id,
                   customer_name=c.name, branch_id=main_branch.id, status='confirmed')
    db.session.add(o); db.session.commit()
    return o


def _open(client, user, branch):
    _login(client, user); _select_branch(client, branch.id)


def _red_element_with(html, text):
    """The opening tag of the element whose own text is `text`, asserted red."""
    m = re.search(r'<(\w+)([^>]*)>\s*%s\s*</\1>' % re.escape(text), html)
    assert m, f'no element renders {text!r}'
    attrs = m.group(2)
    assert 'so-number' in attrs and ('var(--red)' in attrs or '#c00' in attrs), attrs
    return attrs


def test_the_list(client, db_session, admin_user, main_branch, so):
    _open(client, admin_user, main_branch)
    _red_element_with(client.get('/sales-orders?status=all').get_data(as_text=True), SO_NO)


def test_the_detail_page(client, db_session, admin_user, main_branch, so):
    _open(client, admin_user, main_branch)
    _red_element_with(client.get(f'/sales-orders/{so.id}').get_data(as_text=True), SO_NO)


def test_the_entry_form(client, db_session, admin_user, main_branch):
    _open(client, admin_user, main_branch)
    html = client.get('/sales-orders/create').get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="so_number"[^>]*>', html)
    assert tag and 'so-number' in tag.group(0), 'the SO number input is not marked'
    assert '.so-number { color: var(--red)' in html, 'the class has no red rule'


def test_the_standard_printout(client, db_session, admin_user, main_branch, so):
    AppSettings.set_setting('so_print_form', 'current'); db.session.commit()
    _open(client, admin_user, main_branch)
    attrs = _red_element_with(client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True), SO_NO)
    assert 'print-color-adjust:exact' in attrs, 'browsers drop colour when printing without it'


def test_the_preprinted_printout(client, db_session, admin_user, main_branch, so):
    AppSettings.set_setting('so_print_form', 'preprinted'); db.session.commit()
    _open(client, admin_user, main_branch)
    html = client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True)
    assert re.search(r'data-el="so_no"', html), 'anti-vacuity: the so_no field renders'
    assert '[data-el="so_no"] { color: #c00' in html
