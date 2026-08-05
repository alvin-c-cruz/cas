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
    errs = validate_amendment(so, [{'so_item_id': soi.id, 'quantity': '2000'}])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()

    # Exactly delivered (3000) -> allowed.
    errs = validate_amendment(so, [{'so_item_id': soi.id, 'quantity': '3000'}])
    assert errs == []


def test_amendment_against_billed_so(client, db_session, branch, customer, product):
    """Billed SO: a quantity increase is allowed, a decrease is refused, and the
    unit price is frozen.

    Billed-ness is DERIVED from the order's Delivery Receipts (so_is_billed), so
    this builds the state the way the app really produces it -- an invoiced DR --
    rather than setting so.sales_invoice_id, which no code path writes and which
    the guard no longer reads. An earlier version of this test did set that column,
    and so proved the guard fired in a state no user could ever reach.

    No real SalesInvoice row is needed: SQLite FK enforcement is off app-wide and
    the derivation only asks whether dr.sales_invoice_id is set -- the same shape
    app/sales_invoices/views.py writes (dr.sales_invoice_id = invoice.id).
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('5000'))
    soi = so.line_items[0]
    billed_dr = _approved_dr(db_session, branch, customer, so, soi,
                             Decimal('0'), dr_number='DR-BILLED-1')
    billed_dr.sales_invoice_id = 99
    # Left set to prove it is IGNORED -- the derivation must answer from the DR.
    so.sales_invoice_id = None
    db_session.commit()
    db_session.refresh(so)

    from app.delivery_receipts.models import so_is_billed
    assert so_is_billed(so) is True, 'the invoiced DR must make this order billed'

    # Increase -> allowed. Every payload here echoes the STORED unit_price,
    # exactly as the amend form does: _assign_so_line_fields writes
    # item.unit_price = _so_line_dec(d.get('unit_price')), so a payload omitting
    # the key NULLs the price and is a price CHANGE, not a neutral one.
    errs = validate_amendment(
        so, [{'so_item_id': soi.id, 'quantity': '7000', 'unit_price': '4.20'}])
    assert errs == []

    # Decrease -> refused.
    errs = validate_amendment(
        so, [{'so_item_id': soi.id, 'quantity': '4000', 'unit_price': '4.20'}])
    assert len(errs) == 1
    assert 'billed' in errs[0].lower()

    # Price change -> refused, in BOTH directions, against the REAL Numeric
    # column rather than a fake's Decimal. This layer is what proves the
    # comparison survives the round-trip: SQLAlchemy hands back the column's own
    # scale, so a guard that compared FORMATTED STRINGS could pass every
    # unit-level fake and still refuse an untouched price here.
    assert soi.unit_price == Decimal('4.20')
    for changed in ('0.01', '99.00'):
        errs = validate_amendment(
            so, [{'so_item_id': soi.id, 'quantity': '5000',
                  'unit_price': changed}])
        assert len(errs) == 1, errs
        assert 'price' in errs[0].lower()

    # ...and the same price written with different trailing zeros is NOT a
    # change, which is the false-refusal this guard must not produce.
    errs = validate_amendment(
        so, [{'so_item_id': soi.id, 'quantity': '5000', 'unit_price': '4.2'}])
    assert errs == []


def test_exploit_two_tranches_same_product_guarded_independently_real_orm(
        client, db_session, branch, customer, product):
    """THE exploit, proved against real ORM objects and the real so_line_open_qty
    -- not just the unit-test fakes. A confirmed SO carries two lines of the SAME
    product (legitimate: different delivery tranches). One line has a real
    approved Delivery Receipt against it (fully delivered); the other has none.
    Submitting [delivered line -> 0, untouched sibling -> absorb the total] must
    be refused, proving the guard cannot be defeated by aggregating on product_id
    the way the old (defective) implementation did.
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    soi1 = so.line_items[0]

    # A second tranche of the SAME product on the same order.
    from app.sales_orders.models import SalesOrderItem
    soi2 = SalesOrderItem(
        sales_order_id=so.id, line_number=2, product_id=product.id,
        quantity=Decimal('2000'), unit_price=Decimal('4.20'),
        amount=Decimal('8400.00'),
    )
    db_session.add(soi2)
    db_session.commit()
    db_session.refresh(so)

    # Line 1 is fully delivered via a real approved DR.
    _approved_dr(db_session, branch, customer, so, soi1, Decimal('3000'), dr_number='DR-TEST-2')
    db_session.refresh(so)
    db_session.refresh(soi1)
    db_session.refresh(soi2)

    # Exploit shape: zero out the fully-delivered tranche, dump its quantity
    # onto the untouched sibling of the same product.
    errs = validate_amendment(so, [
        {'so_item_id': soi1.id, 'quantity': '0'},
        {'so_item_id': soi2.id, 'quantity': '5000'},
    ])
    assert len(errs) == 1
    assert '3000' in errs[0] and 'delivered' in errs[0].lower()
