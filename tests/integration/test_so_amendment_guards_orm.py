"""Integration (ORM-seam) tests -- post-confirm amendment guards.

test_so_amendment_guards.py proves the branching logic against dict-shaped fake
lines and a monkeypatched so_line_open_qty. That is deliberate for unit-testing
the branches in isolation, but it never crosses the ORM boundary -- and on this
branch a defect already survived multiple reviews precisely because every test
was dict-shaped. These tests build a real confirmed Sales Order, a real
Delivery Receipt row, and call validate_amendment with the REAL so_line_open_qty
(no monkeypatch) so the guard is proved against what the ORM actually returns.
"""
import json
import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.revisions import validate_amendment
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem

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
        # Branch.code is NOT NULL/unique -- omit it and the insert fails.
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


# --- shared helper ------------------------------------------------------------

def _confirmed_so(client, db_session, customer, product, qty, so_number='2026080001'):
    """Create a draft SO through the route, then confirm it through the route.

    Deliberately drives both routes rather than building rows directly, matching
    test_so_amendment.py's pattern.
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


def _approved_dr(db_session, branch, customer, so, soi, delivered_qty, dr_number='DR-TEST-1'):
    """A real, committed (approved) Delivery Receipt row -- built directly through
    the ORM (not the /delivery-receipts route: approving there requires an
    accountant/admin role, which is orthogonal to what these tests are proving).
    status='approved' is in DeliveryReceipt.COMMITTED_STATUSES, so this quantity
    is counted by the real so_line_open_qty.
    """
    dr = DeliveryReceipt(
        branch_id=branch.id, dr_number=dr_number, delivery_date=date(2026, 8, 4),
        sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
        status='approved',
    )
    dr.line_items.append(DeliveryReceiptItem(
        line_number=1, sales_order_item_id=soi.id, product_id=soi.product_id,
        delivered_quantity=Decimal(str(delivered_qty)),
    ))
    db_session.add(dr)
    db_session.commit()
    return dr


# --- tests ---------------------------------------------------------------------

def test_amendment_against_partially_delivered_line(client, db_session, branch, customer, product):
    """Confirmed SO, real approved DR delivering part of the line: reducing BELOW
    the delivered quantity is refused; reducing to EXACTLY the delivered quantity
    is allowed. Uses the real so_line_open_qty -- no monkeypatch.
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('5000'))
    soi = so.line_items[0]
    _approved_dr(db_session, branch, customer, so, soi, Decimal('3000'))
    db_session.refresh(so)
    db_session.refresh(soi)

    # Below delivered (3000) -> refused.
    errs = validate_amendment(so, [{'product_id': soi.product_id, 'quantity': '2000'}])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()

    # Exactly delivered (3000) -> allowed.
    errs = validate_amendment(so, [{'product_id': soi.product_id, 'quantity': '3000'}])
    assert errs == []


def test_amendment_against_billed_so(client, db_session, branch, customer, product):
    """Billed SO (sales_invoice_id set): an increase is allowed, a decrease is
    refused. No real SalesInvoice row is needed -- SQLite FK enforcement is off
    app-wide, and the guard only reads so.sales_invoice_id is not None.
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('5000'))
    soi = so.line_items[0]
    so.sales_invoice_id = 99
    db_session.commit()
    db_session.refresh(so)

    # Increase -> allowed.
    errs = validate_amendment(so, [{'product_id': soi.product_id, 'quantity': '7000'}])
    assert errs == []

    # Decrease -> refused.
    errs = validate_amendment(so, [{'product_id': soi.product_id, 'quantity': '4000'}])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()
