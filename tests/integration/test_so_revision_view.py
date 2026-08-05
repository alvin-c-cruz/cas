"""Integration tests -- reading a stored Sales Order revision."""
import json
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


# --- fixtures local to this file (mirrors test_so_amendment.py) -------------

@pytest.fixture
def branch(db_session):
    from app.branches.models import Branch
    b = Branch.query.first()
    if b is None:
        # Branch.code is NOT NULL/unique -- the brief's snippet omitted it.
        b = Branch(code='CORP', name='CORP')
        db_session.add(b)
        db_session.commit()
    return b


@pytest.fixture
def customer(db_session):
    return _customer(db_session)


@pytest.fixture
def product(db_session):
    _enable_products(db_session)
    return _product(db_session)


@pytest.fixture
def staff_user(db_session, branch):
    """A staff user -- amendment (and viewing revisions) must be reachable by
    staff, not just accountants."""
    from app.users.models import User
    u = User(username='china', email='china@example.com', full_name='China',
             role='staff', is_active=True, branch_id=branch.id)
    u.set_password('uitest-Pass123!')
    # sales_orders is per_user-gated (module_access.py); staff is also
    # branch-scoped (User.branches, many-to-many).
    u.set_book_permissions({'sales_orders': True})
    db_session.add(u)
    db_session.flush()  # get u.id before set_branches
    u.set_branches([branch])
    db_session.commit()
    return u


@pytest.fixture
def client(client, db_session, staff_user, branch):
    """Logged-in, branch-selected client -- every test below needs both."""
    _login(client, staff_user)
    _select_branch(client, branch.id)
    return client


# --- shared helpers -----------------------------------------------------------

def _confirmed_so(client, db_session, customer, product, qty,
                  so_number='2026080001'):
    """Create a draft SO through the route, then confirm it through the route.

    Deliberately drives both routes rather than building rows directly, so Rev 0
    is written by the code under test.
    """
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': str(qty), 'unit_price': '4.20',
                         'amount': str(qty * Decimal('4.20'))}])
    client.post('/sales-orders/create', data={
        'so_number': so_number, 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number=so_number).one()
    client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'confirmed'
    return so


def _amend_to(client, so, product, qty,
              reason='PO received after job order issued', po='PO-MMS-88421'):
    """Amend *so* to a new single-line quantity through the amend route."""
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': str(qty), 'unit_price': '4.20',
                         'amount': str(qty * Decimal('4.20'))}])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': so.so_number, 'order_date': '2026-08-04',
        'customer_id': str(so.customer_id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines,
        'amend_reason': reason, 'authorizing_po_number': po,
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200
    return resp


def test_rev0_shows_the_order_AS_CONFIRMED_not_as_it_is_now(
        client, db_session, customer, product):
    """THE test for this feature. After amending 3,000 -> 7,000, Rev 0 must still
    render 3,000 -- it is the record of what production was told to make. If this
    renders live data instead of the snapshot, the whole feature is decorative."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    _amend_to(client, so, product, Decimal('7000'))

    html = client.get(f'/sales-orders/{so.id}/revisions/0').data.decode()
    assert '3,000' in html
    assert '7,000' not in html


def test_latest_revision_shows_the_amended_figures(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    _amend_to(client, so, product, Decimal('7000'))
    html = client.get(f'/sales-orders/{so.id}/revisions/1').data.decode()
    assert '7,000' in html


def test_revision_view_shows_who_when_and_why(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    _amend_to(client, so, product, Decimal('7000'),
              reason='PO received after job order issued', po='PO-MMS-88421')
    html = client.get(f'/sales-orders/{so.id}/revisions/1').data.decode()
    assert 'PO received after job order issued' in html
    assert 'PO-MMS-88421' in html


def test_unknown_revision_number_404s(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    assert client.get(f'/sales-orders/{so.id}/revisions/99').status_code == 404


def test_revision_of_an_so_in_another_branch_404s(client, db_session, customer, product):
    """Same branch scope as every other route in this module."""
    from app.branches.models import Branch
    other = Branch(code='EXTRA', name='EXTRA')
    db_session.add(other)
    db_session.commit()
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    so.branch_id = other.id
    db_session.commit()
    assert client.get(f'/sales-orders/{so.id}/revisions/0').status_code == 404


def test_the_panel_links_to_each_revision(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    _amend_to(client, so, product, Decimal('7000'))
    html = client.get(f'/sales-orders/{so.id}').data.decode()
    # Full attribute, not a bare token.
    assert f'href="/sales-orders/{so.id}/revisions/0"' in html
    assert f'href="/sales-orders/{so.id}/revisions/1"' in html


def test_the_viewer_is_read_only(client, db_session, customer, product):
    """A snapshot is a historical record; it must offer no way to act on it."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}/revisions/0').data.decode()
    for forbidden in ('/amend', '/confirm', '/cancel', '<form'):
        assert forbidden not in html


def test_money_fields_render_with_thousands_separators(
        client, db_session, customer, product):
    """Money fields (unit price, amount, totals) must render with comma grouping.

    This is a financial document; ungrouped six-figure values (12600.00) are less
    readable than grouped (12,600.00) and break app convention.
    """
    # Create and confirm with a quantity that produces observable grouping
    qty = Decimal('12600')
    unit_price = Decimal('4.20')
    so = _confirmed_so(client, db_session, customer, product, qty)

    html = client.get(f'/sales-orders/{so.id}/revisions/0').data.decode()

    # Line-item unit price and amount must show grouped form
    expected_unit_price = '{:,.2f}'.format(unit_price)  # '4.20'
    expected_amount = '{:,.2f}'.format(qty * unit_price)  # '52,920.00'
    expected_subtotal = '{:,.2f}'.format(qty * unit_price)

    assert expected_amount in html, f"Grouped amount '{expected_amount}' not found in response"
    # Ungrouped form must NOT appear (this catches both unformatted and
    # formatter-on-None crashes)
    assert '52920.00' not in html, "Ungrouped amount still present in response"

    # Subtotal in the totals block must also be grouped
    assert expected_subtotal in html, f"Grouped subtotal '{expected_subtotal}' not found"
