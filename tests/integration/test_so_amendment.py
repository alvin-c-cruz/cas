"""Integration tests -- SO post-confirm amendment."""
import json
import pytest
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision
from app.customers.models import Customer

from tests.integration._so_helpers import (
    sales_orders_module_enabled, _login, _select_branch,
    _customer, _product, _enable_products,
)

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


# --- fixtures local to this file -------------------------------------------

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
    """A staff user -- amendment must be reachable by staff, not just accountants."""
    from app.users.models import User
    u = User(username='china', email='china@example.com', full_name='China',
             role='staff', is_active=True, branch_id=branch.id)
    u.set_password('uitest-Pass123!')
    # sales_orders is per_user-gated (module_access.py); staff is also branch-scoped
    # (User.branches, many-to-many) -- the brief's snippet set the scalar branch_id
    # column only, which the before_request accessible-branches check does not read,
    # so the client fixture below force-logs the user out at the branch picker.
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


# --- shared helper ----------------------------------------------------------

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


def test_confirm_writes_revision_zero(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    revs = SalesOrderRevision.query.filter_by(sales_order_id=so.id).all()
    assert len(revs) == 1
    rev0 = revs[0]
    assert rev0.revision_number == 0
    assert rev0.reason is None
    snap = json.loads(rev0.snapshot_json)
    assert snap['lines'][0]['quantity'] == '3000'
    assert snap['header']['status'] == 'confirmed'
