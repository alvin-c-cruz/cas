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
def accountant_user(db_session, branch):
    """An accountant user -- close_line's role gate is accountant/admin, not staff."""
    from app.users.models import User
    u = User(username='ana', email='ana@example.com', full_name='Ana',
             role='accountant', is_active=True, branch_id=branch.id)
    u.set_password('uitest-Pass123!')
    u.set_book_permissions({'sales_orders': True})
    db_session.add(u)
    db_session.flush()  # get u.id before set_branches
    u.set_branches([branch])
    db_session.commit()
    return u


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
                  so_number='2026080001', second_line_qty=None):
    """Create a draft SO through the route, then confirm it through the route.

    Deliberately drives both routes rather than building rows directly, so Rev 0
    is written by the code under test.

    second_line_qty, when given, adds a SECOND line (same product) to the initial
    submission -- for tests that need to close one line while amending the other.
    Existing call sites are unaffected: default None keeps the single-line shape.
    """
    line_list = [{'line_number': 1, 'product_id': product.id,
                  'quantity': str(qty), 'unit_price': '4.20',
                  'amount': str(qty * Decimal('4.20'))}]
    if second_line_qty is not None:
        line_list.append({'line_number': 2, 'product_id': product.id,
                          'quantity': str(second_line_qty), 'unit_price': '4.20',
                          'amount': str(second_line_qty * Decimal('4.20'))})
    lines = json.dumps(line_list)
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


def test_amend_increases_quantity_and_writes_rev1(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20',
                         'amount': '29400.00'}])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200

    db_session.refresh(so)
    assert so.status == 'confirmed'
    assert so.line_items[0].quantity == Decimal('7000')

    revs = (SalesOrderRevision.query.filter_by(sales_order_id=so.id)
            .order_by(SalesOrderRevision.revision_number).all())
    assert [r.revision_number for r in revs] == [0, 1]
    assert revs[1].reason == 'PO received after job order issued'
    assert revs[1].authorizing_po_number == 'PO-MMS-88421'
    assert json.loads(revs[0].snapshot_json)['lines'][0]['quantity'] == '3000'
    # The revision records what the order WAS -- assert the snapshot itself,
    # since nothing computes a diff.
    assert json.loads(revs[1].snapshot_json)['lines'][0]['quantity'] == '7000'


def test_amend_refuses_short_reason(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'too short',
        'authorizing_po_number': 'PO-1', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    db_session.refresh(so)
    assert so.line_items[0].quantity == Decimal('3000')
    assert SalesOrderRevision.query.filter_by(sales_order_id=so.id).count() == 1


def test_amend_refuses_on_a_draft_so(client, db_session, customer, product):
    """Drafts use edit(); amend must refuse them."""
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'}])
    client.post('/sales-orders/create', data={
        'so_number': '2026080002', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='2026080002').one()
    resp = client.get(f'/sales-orders/{so.id}/amend', follow_redirects=True)
    assert b'Only confirmed Sales Orders can be amended' in resp.data


def test_amend_requires_authorizing_po_when_customer_requires_po(
        client, db_session, customer, product):
    # NOTE: po_required is set AFTER confirming, not before -- confirm() has its
    # own pre-existing guard (views.py: "Customer ... requires a Purchase Order
    # number before this Sales Order can be confirmed") that refuses to confirm
    # a draft with no customer_po_number once po_required is on. Setting the
    # flag before _confirmed_so would make the helper's own confirm() step fail
    # for a reason unrelated to amendment. Flagging the customer po_required
    # AFTER confirmation (a realistic sequence -- the requirement can be turned
    # on any time) isolates the thing this test actually checks: the amend
    # route's own authorizing_po_number guard.
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    customer.po_required = True
    db_session.commit()
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order',
        'authorizing_po_number': '', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    db_session.refresh(so)
    assert so.line_items[0].quantity == Decimal('3000')


def test_amend_is_reachable_by_staff(client, db_session, customer, product):
    """Guard 0 -- the gate is _role_gate(), NOT cancel()'s accountant-only gate.
    The `client` fixture is logged in as a staff user, so a 200 proves it."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    assert client.get(f'/sales-orders/{so.id}/amend').status_code == 200


def test_amend_refused_for_viewer(client, db_session, customer, product, staff_user):
    """Guard 0, the other direction -- viewer is the one excluded role."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    staff_user.role = 'viewer'
    db_session.commit()
    import flask
    flask.g.pop('_login_user', None)
    resp = client.get(f'/sales-orders/{so.id}/amend', follow_redirects=True)
    assert b'do not have permission' in resp.data


def test_amend_404s_for_an_so_in_another_branch(client, db_session, customer, product):
    """Guard 7 -- branch scope, matching every other route in the module."""
    from app.branches.models import Branch
    other = Branch(code='EXTRA', name='EXTRA')
    db_session.add(other)
    db_session.commit()
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    so.branch_id = other.id
    db_session.commit()
    assert client.get(f'/sales-orders/{so.id}/amend').status_code == 404


def test_amend_refuses_a_stale_row_version(client, db_session, customer, product):
    """Guard 8 -- optimistic lock; a concurrent amendment must not be clobbered."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    stale = so.row_version - 1
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421', 'row_version': str(stale),
    }, follow_redirects=True)
    db_session.refresh(so)
    assert so.line_items[0].quantity == Decimal('3000')
    assert SalesOrderRevision.query.filter_by(sales_order_id=so.id).count() == 1


def test_amend_ignores_foreign_so_item_id(client, db_session, customer, product):
    """Security pin for _apply_amended_so_lines: a submitted so_item_id that
    belongs to a DIFFERENT Sales Order must never be resolved against it. The
    lookup dict is built from THIS order's own so.line_items only -- a global
    db.session.get(SalesOrderItem, id) would let one order's amendment rewrite
    another order's line, and validate_amendment (which ignores an id it does
    not recognise) would not catch it either."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'),
                       so_number='2026080001')
    other_so = _confirmed_so(client, db_session, customer, product, Decimal('5000'),
                             so_number='2026080003')
    other_item = other_so.line_items[0]
    other_item_id = other_item.id
    other_qty, other_price, other_status = (
        other_item.quantity, other_item.unit_price, other_item.line_status)
    own_item_id = so.line_items[0].id

    # Submit AGAINST so (this order): the order's OWN existing line, unchanged,
    # PLUS an attack line carrying the OTHER order's line id. If the lookup were
    # not scoped, the attack line would resolve to -- and overwrite -- the other
    # order's row instead of creating a new one on this order.
    lines = json.dumps([
        {'so_item_id': own_item_id, 'line_number': 1, 'product_id': product.id,
         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'},
        {'so_item_id': other_item_id, 'line_number': 2,
         'product_id': product.id, 'quantity': '9000',
         'unit_price': '4.20', 'amount': '37800.00'},
    ])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Testing foreign so_item_id is not resolved',
        'authorizing_po_number': 'PO-SEC-1',
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200

    # The other order's row is byte-identical -- untouched.
    db_session.refresh(other_item)
    assert other_item.quantity == other_qty
    assert other_item.unit_price == other_price
    assert other_item.line_status == other_status

    # THIS order got a NEW line instead of overwriting the foreign row.
    db_session.refresh(so)
    assert len(so.line_items) == 2
    quantities = sorted(i.quantity for i in so.line_items)
    assert quantities == sorted([Decimal('3000'), Decimal('9000')])


def test_amending_does_not_reopen_a_closed_line(
        client, db_session, customer, product, accountant_user, staff_user, branch):
    """The single most important reason _apply_amended_so_lines updates rows IN
    PLACE rather than deleting-and-rebuilding: a rebuild resets line_status to
    'open', silently RE-OPENING a line someone deliberately short-closed and
    discarding closed_by_id/closed_at/closed_reason with it. This was reasoned
    about but never exercised -- pin it."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'),
                       second_line_qty=Decimal('1000'))
    items = sorted(so.line_items, key=lambda i: i.line_number)
    closed_item, open_item = items[0], items[1]
    closed_item_id, open_item_id = closed_item.id, open_item.id

    # Close line 1 through the real route, as an accountant -- close_line's role
    # gate is accountant/admin, not staff.
    _login(client, accountant_user)
    _select_branch(client, branch.id)
    resp = client.post(f'/sales-orders/{so.id}/lines/{closed_item_id}/close',
                       data={'closed_reason': 'Customer cancelled this tranche'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(closed_item)
    assert closed_item.line_status == 'closed', (
        'setup failed: the close route did not actually close the line')
    recorded_by = closed_item.closed_by_id
    recorded_at = closed_item.closed_at
    recorded_reason = closed_item.closed_reason
    assert recorded_by == accountant_user.id
    assert recorded_reason == 'Customer cancelled this tranche'

    # Amend as staff, changing only the OTHER (open) line's quantity. The closed
    # line's submitted quantity stays equal to its current value -- validate_amendment
    # separately refuses a quantity change on a closed line; that is not what this
    # test is checking.
    _login(client, staff_user)
    _select_branch(client, branch.id)
    db_session.refresh(so)
    lines = json.dumps([
        {'so_item_id': closed_item_id, 'line_number': 1, 'product_id': product.id,
         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'},
        {'so_item_id': open_item_id, 'line_number': 2, 'product_id': product.id,
         'quantity': '5000', 'unit_price': '4.20', 'amount': '21000.00'},
    ])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Increase remaining open line quantity',
        'authorizing_po_number': 'PO-CLOSE-1',
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200

    db_session.refresh(so)
    open_item_after = next(i for i in so.line_items if i.id == open_item_id)
    assert open_item_after.quantity == Decimal('5000')

    db_session.refresh(closed_item)
    assert closed_item.line_status == 'closed'
    assert closed_item.closed_by_id == recorded_by
    assert closed_item.closed_at == recorded_at
    assert closed_item.closed_reason == recorded_reason


def test_a_client_cannot_reopen_a_closed_line_through_the_amend_form(
        client, db_session, customer, product, accountant_user, staff_user, branch):
    """A crafted amend POST that additionally carries line_status/closed_by_id/
    closed_at/closed_reason for a closed line -- trying to launder a re-open
    through the form -- must be ignored entirely. These are not form fields;
    _assign_so_line_fields never reads or writes them."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'),
                       second_line_qty=Decimal('1000'))
    items = sorted(so.line_items, key=lambda i: i.line_number)
    closed_item, open_item = items[0], items[1]
    closed_item_id, open_item_id = closed_item.id, open_item.id

    _login(client, accountant_user)
    _select_branch(client, branch.id)
    resp = client.post(f'/sales-orders/{so.id}/lines/{closed_item_id}/close',
                       data={'closed_reason': 'Customer cancelled this tranche'},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(closed_item)
    assert closed_item.line_status == 'closed', (
        'setup failed: the close route did not actually close the line')
    recorded_by = closed_item.closed_by_id
    recorded_at = closed_item.closed_at
    recorded_reason = closed_item.closed_reason

    _login(client, staff_user)
    _select_branch(client, branch.id)
    db_session.refresh(so)
    lines = json.dumps([
        {'so_item_id': closed_item_id, 'line_number': 1, 'product_id': product.id,
         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00',
         'line_status': 'open', 'closed_by_id': None, 'closed_at': None,
         'closed_reason': None},
        {'so_item_id': open_item_id, 'line_number': 2, 'product_id': product.id,
         'quantity': '1000', 'unit_price': '4.20', 'amount': '4200.00'},
    ])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Attempt to launder a reopen through the amend form',
        'authorizing_po_number': 'PO-CLOSE-2',
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200

    db_session.refresh(closed_item)
    assert closed_item.line_status == 'closed'
    assert closed_item.closed_by_id == recorded_by
    assert closed_item.closed_at == recorded_at
    assert closed_item.closed_reason == recorded_reason
