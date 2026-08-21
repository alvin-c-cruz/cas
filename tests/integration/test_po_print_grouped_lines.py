"""The PO printout groups its lines under Description headings.

Owner directive 2026-08-21: "the PO should be grouped by the Description field
instead."

Two things were wrong with the flat table. It listed every line separately with
no sense of what each was FOR, and -- the sharper defect -- a line's description
was dropped entirely whenever the line carried a product:

    {{ li.product.name if li.product else li.description }}

so "FOR BOILER USE", typed by the buyer against a COAL line, reached no printed
page at all. The ordering logic itself is unit-tested in
tests/unit/test_po_group_lines_by_description.py; this file covers what actually
renders.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _po(db_session, main_branch, vendor, number, lines):
    """lines: [(line_number, description, product_or_None, amount), ...]"""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, branch_id=main_branch.id,
                       # NOT draft: po_print_access is default-deny for drafts,
                       # so a draft would 302 and every assertion below would be
                       # vacuous (it caught exactly that on the first RED run).
                       status='approved')
    db.session.add(po); db.session.flush()
    total = Decimal('0')
    for n, desc, product, amount in lines:
        amt = Decimal(str(amount))
        total += amt
        db.session.add(PurchaseOrderItem(
            purchase_order_id=po.id, line_number=n, description=desc,
            product_id=product.id if product else None,
            quantity=Decimal('1'), unit_price=amt, amount=amt, line_total=amt))
    po.total_amount = total
    db.session.commit()
    return po


def _print(client, po):
    r = client.get(f'/purchase-orders/{po.id}/print')
    assert r.status_code == 200, f'print route returned {r.status_code}'
    return r.get_data(as_text=True)


def _headings(html):
    return re.findall(r'<td class="grp"[^>]*>(.*?)</td>', html, re.S)


def _subtotals(html):
    return re.findall(r'class="num grp-sub">([\d,.]+)</td>', html)


def test_lines_group_under_their_description_in_first_appearance_order(
        client, db_session, accountant_user, main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-1', [
        (1, 'ZINC WORKS', None, 100),
        (2, 'ALUMINIUM WORKS', None, 250),
        (3, 'ZINC WORKS', None, 50),
    ])
    _login(client, accountant_user, main_branch)

    headings = [h.strip() for h in _headings(_print(client, po))]
    assert headings == ['ZINC WORKS', 'ALUMINIUM WORKS'], \
        'headings are alphabetical -- the buyer order was reshuffled'


def test_each_group_prints_its_subtotal(client, db_session, accountant_user, main_branch,
                                        vl_vendor):
    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-2', [
        (1, 'A', None, 100), (2, 'B', None, 250), (3, 'A', None, 50),
    ])
    _login(client, accountant_user, main_branch)

    assert _subtotals(_print(client, po)) == ['150.00', '250.00']


def test_a_single_group_prints_no_subtotal_row(client, db_session, accountant_user,
                                               main_branch, vl_vendor):
    """A lone subtotal directly above an identical Total reads as a mistake.

    This is the shape of the owner's real PO 00001 -- one line, one description.
    """
    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-3', [
        (1, 'FOR BOILER USE', None, 250000),
    ])
    _login(client, accountant_user, main_branch)
    html = _print(client, po)

    assert [h.strip() for h in _headings(html)] == ['FOR BOILER USE']
    assert _subtotals(html) == [], 'a single group should not repeat itself as a subtotal'
    assert '250,000.00' in html          # the Total still prints


def test_a_description_prints_even_when_the_line_has_a_product(
        client, db_session, accountant_user, main_branch, vl_vendor):
    """The original defect: a product on the line hid the description entirely."""
    from app.products.models import Product
    p = Product(code='COAL-T', name='COAL', is_active=True)
    db.session.add(p); db.session.commit()

    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-4', [
        (1, 'FOR BOILER USE', p, 250000),
    ])
    _login(client, accountant_user, main_branch)
    html = _print(client, po)

    assert 'FOR BOILER USE' in html, 'the description is still being dropped'
    assert 'COAL' in html, 'the product name stopped printing'


def test_undescribed_lines_print_without_a_heading(client, db_session, accountant_user,
                                                   main_branch, vl_vendor):
    """CONTROL: a line with no description must not vanish off a supplier's copy."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-5', [
        (1, None, None, 10), (2, 'A', None, 5),
    ])
    _login(client, accountant_user, main_branch)
    html = _print(client, po)

    assert [h.strip() for h in _headings(html)] == ['A'], \
        'an empty heading row was drawn for the undescribed group'

    # Both lines still print -- the undescribed one is not silently dropped.
    body = html[html.index('<tbody>'):html.index('</tbody>')]
    line_cells = re.findall(r'<tr>\s*<td>(\d+)</td>', body)
    assert line_cells == ['1', '2'], f'expected both lines, got {line_cells}'

    # The undescribed group is a real group, so it subtotals like any other:
    # two groups here, hence two subtotals.
    assert _subtotals(html) == ['10.00', '5.00']


def test_the_grand_total_is_unchanged(client, db_session, accountant_user, main_branch,
                                      vl_vendor):
    """CONTROL: grouping is presentation. The header total still governs the foot."""
    po = _po(db_session, main_branch, vl_vendor, 'PO-GRP-6', [
        (1, 'A', None, 100), (2, 'B', None, 250),
    ])
    _login(client, accountant_user, main_branch)
    html = _print(client, po)

    foot = html[html.index('<tfoot>'):]
    assert '350.00' in foot
