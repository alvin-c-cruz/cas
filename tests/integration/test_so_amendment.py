"""Integration tests -- SO post-confirm amendment."""
import json
import re
import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.revision_models import SalesOrderRevision
from app.customers.models import Customer, CustomerDeliverySite
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem

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
    # job_order_slips is its OWN grantable module (Task 5) -- print_job_order's
    # endpoint is registered under that key, not sales_orders, so a Task 9 print
    # test that hits it needs this too (see _so_helpers.py's module-enable note).
    u.set_book_permissions({'sales_orders': True, 'job_order_slips': True})
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
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order',
        'authorizing_po_number': '', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    db_session.refresh(so)
    assert so.line_items[0].quantity == Decimal('3000')
    # Assert WHICH refusal fired. "quantity unchanged" is satisfied by ANY
    # refusal -- a broken reason rule, a row_version regression, even a 500 --
    # so on its own it does not pin validate_authorizing_po_number at all.
    assert b'requires a Purchase Order number' in resp.data


def test_a_blank_authorizing_po_is_fine_when_the_customer_does_not_require_one(
        client, db_session, customer, product):
    """The negative direction. Without this, someone 'fixing' the missing
    Optional() by reaching for DataRequired() would break nothing visible."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'so_item_id': so.line_items[0].id, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'Customer increased by phone',
        'authorizing_po_number': '', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    db_session.refresh(so)
    assert so.line_items[0].quantity == Decimal('7000')


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
    # Full sentence: five other modules emit the same fragment.
    assert b'You do not have permission to perform this action.' in resp.data


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
def test_amend_does_not_silently_drop_a_new_line_via_autoflush(
        client, db_session, customer, product):
    """CRITICAL. _apply_amended_so_lines's original sweep iterated the LIVE
    so.line_items collection. A newly added line's id starts out None, but it
    does not stay that way: the per-line loop calls _so_line_delivery_site_id ->
    db.session.get(CustomerDeliverySite, ...), and on a cache miss SQLAlchemy
    AUTOFLUSHES before running that SELECT -- which INSERTs any other pending
    new SalesOrderItem already added to the session and assigns it a real id.
    That id was never added to `seen` (only matched EXISTING ids are), so the
    live-collection sweep deleted the line the user had just added -- silently,
    with a success flash, and with the loss baked into the revision snapshot as
    though it were intentional.

    Reproduced through the real route: submitting [existing 3000, NEW 111,
    NEW 222-with-delivery-site] returned HTTP 200 with an "amended (Rev 1)"
    success flash and saved only TWO lines.

    The bug reproduces ONLY across a real session/identity-map boundary. If the
    delivery site stayed in this test's identity map (e.g. freshly created and
    left attached), db.session.get would resolve it from memory with NO
    autoflush and NO SELECT at all, and the bug would not reproduce -- so the
    site is expunged below to mimic a real request boundary, where the site row
    was created in an earlier, separate transaction.
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    existing_item_id = so.line_items[0].id

    site = CustomerDeliverySite(customer_id=customer.id, name='Warehouse A')
    db_session.add(site)
    db_session.commit()
    site_id = site.id
    db_session.expunge(site)  # simulate a fresh request: site not in the identity map

    lines = json.dumps([
        {'so_item_id': existing_item_id, 'line_number': 1, 'product_id': product.id,
         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'},
        {'line_number': 2, 'product_id': product.id,
         'quantity': '111', 'unit_price': '4.20', 'amount': '466.20'},
        {'line_number': 3, 'product_id': product.id,
         'quantity': '222', 'unit_price': '4.20', 'amount': '932.40',
         'delivery_site_id': site_id},
    ])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Customer added two more lines by phone',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'amended (Rev 1)' in resp.data

    db_session.refresh(so)
    db_session.expire(so, ['line_items'])
    quantities = sorted(i.quantity for i in so.line_items)
    assert quantities == [Decimal('111'), Decimal('222'), Decimal('3000')], (
        'a newly added line was silently dropped by the autoflush-blind sweep')
    assert so.total_amount == Decimal('12600.00') + Decimal('466.20') + Decimal('932.40')


def test_amend_refuses_to_remove_a_line_referenced_by_a_draft_dr(
        client, db_session, branch, customer, product):
    """IMPORTANT. validate_amendment's removal checks looked only at
    _delivered_qty (which counts COMMITTED_STATUSES DRs -- approved/delivered/
    billed) and `billed`. A DRAFT (or cancelled) DR contributes zero to that
    count, so removing the SO line it references passed validation and deleted
    the row. SQLite FK enforcement is off app-wide, so this left the DR line's
    sales_order_item_id dangling -- the next so_line_open_qty(li.sales_order_item)
    call on that DR (e.g. on approve) dereferences None and 500s, unrecoverable
    through the UI. Guard it status-agnostically: ANY DR reference blocks
    removal, draft included.

    A DRAFT DR is used deliberately, not an approved one -- an approved DR is
    already blocked by the delivered-quantity check, so testing with one would
    prove nothing about this new guard.
    """
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    soi = so.line_items[0]

    dr = DeliveryReceipt(
        branch_id=branch.id, dr_number='DR-DRAFT-1', delivery_date=date(2026, 8, 4),
        sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
        status='draft')
    dr.line_items.append(DeliveryReceiptItem(
        line_number=1, sales_order_item_id=soi.id, product_id=soi.product_id,
        delivered_quantity=Decimal('0')))
    db_session.add(dr)
    db_session.commit()

    lines = json.dumps([])  # submit with the SO's only line removed
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Attempting to remove a DR-referenced line',
        'authorizing_po_number': 'PO-DR-1', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Delivery Receipt' in resp.data

    db_session.refresh(so)
    assert len(so.line_items) == 1
    assert so.line_items[0].id == soi.id


def test_amend_saves_a_changed_order_date(client, db_session, customer, product):
    """IMPORTANT. edit() assigns order_date onto the SO; amend() did not, and
    nothing renders the field read-only -- a changed order_date validated
    cleanly (it IS a real form field) but was silently discarded on save."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'so_item_id': so.line_items[0].id, 'line_number': 1,
                         'product_id': product.id, 'quantity': '3000',
                         'unit_price': '4.20', 'amount': '12600.00'}])
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-10',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'Order date corrected per customer call',
        'authorizing_po_number': 'PO-DATE-1', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200

    db_session.refresh(so)
    assert so.order_date == date(2026, 8, 10)


def test_amend_refuses_removal_of_a_delivered_line_with_the_delivered_message(
        client, db_session, branch, customer, product):
    """PINS THE GUARD ORDER: delivered > 0 must be checked BEFORE
    _has_any_dr_reference. Every DR that commits real quantity (approved/
    delivered/billed) ALSO matches the reference check -- so an approved DR
    with delivered_quantity > 0 satisfies BOTH guards. If the reference check
    ran first (as it originally did), this case would always report the
    generic 'Cancel or amend that Delivery Receipt' message instead of the
    specific 'Close the line' remedy this module actually provides -- and
    cancelling an approved DR reverses real stock/COGS postings, a much
    heavier action than closing the line. Assert the DR-reference wording is
    ABSENT: a substring shared between refusals proves nothing about which one
    fired."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    soi = so.line_items[0]

    dr = DeliveryReceipt(
        branch_id=branch.id, dr_number='DR-APPROVED-1', delivery_date=date(2026, 8, 4),
        sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
        status='approved')
    dr.line_items.append(DeliveryReceiptItem(
        line_number=1, sales_order_item_id=soi.id, product_id=soi.product_id,
        delivered_quantity=Decimal('1000')))
    db_session.add(dr)
    db_session.commit()

    lines = json.dumps([])  # submit with the SO's only line removed
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Attempting to remove a line already delivered against',
        'authorizing_po_number': 'PO-DELIVERED-1', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already delivered. Close the line instead to stop further delivery.' in resp.data
    assert b'referenced by a Delivery Receipt' not in resp.data

    db_session.refresh(so)
    assert len(so.line_items) == 1
    assert so.line_items[0].id == soi.id


def test_detail_shows_amend_button_on_confirmed_so(client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}').data.decode()
    assert f'href="/sales-orders/{so.id}/amend"' in html


def test_detail_hides_amend_button_on_draft_so(client, db_session, customer, product):
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'}])
    client.post('/sales-orders/create', data={
        'so_number': '2026080003', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='2026080003').one()
    html = client.get(f'/sales-orders/{so.id}').data.decode()
    assert f'href="/sales-orders/{so.id}/amend"' not in html


def test_detail_lists_every_revision_with_reason_and_po(
        client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version)}, follow_redirects=True)

    html = client.get(f'/sales-orders/{so.id}').data.decode()
    assert 'Revision history' in html
    assert 'Rev 1' in html and 'Rev 0' in html
    assert 'PO received after job order issued' in html
    assert 'PO-MMS-88421' in html
    # There is no computed change summary (owner decision 2026-08-04, option B) --
    # the panel itself carries no line data. What the page DOES guarantee is that
    # the line-items table reflects the post-amendment state: the line was
    # updated IN PLACE (Task 6), so the amended quantity renders and the
    # superseded original does not linger anywhere on the page.
    # Compared as whole CELL values, not substrings. With trailing zeros now
    # trimmed, a bare '3,000' would also match the money figure '3,000.00',
    # so the negative assertion would fail for the wrong reason -- the 4dp
    # form used to make a quantity unmistakable on its own.
    import re
    qty_cells = [m.strip() for m in
                 re.findall(r'<td[^>]*var\(--mono\)[^>]*>\s*([^<]*?)\s*</td>', html)]
    assert '7,000' in qty_cells
    assert '3,000' not in qty_cells


def test_detail_has_no_revision_panel_when_never_amended_beyond_rev0(
        client, db_session, customer, product):
    """Rev 0 alone still shows the panel -- it is the original-order record."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}').data.decode()
    assert 'Revision history' in html
    assert 'Rev 0' in html
    assert 'Rev 1' not in html


def test_detail_hides_amend_button_on_cancelled_so(client, db_session, customer, product):
    """The Amend button gates on status == 'confirmed' only -- a cancelled SO
    must not offer it either, not just a draft."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    so.status = 'cancelled'
    db_session.commit()
    html = client.get(f'/sales-orders/{so.id}').data.decode()
    assert f'href="/sales-orders/{so.id}/amend"' not in html


def test_amend_form_renders_so_number_read_only(client, db_session, customer, product):
    """so_number must render read-only in amend mode -- assert the FULL <input>
    tag carries the attribute, not a bare 'readonly' token that could match an
    unrelated field elsewhere on the page."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}/amend').data.decode()
    m = re.search(r'<input[^>]*name="so_number"[^>]*>', html)
    assert m is not None, 'so_number input not found in the amend form'
    assert 'readonly' in m.group(0)


def test_amend_form_serialises_so_item_id_on_submit(client, db_session, customer, product):
    """The whole in-place-update design (see revisions.py's validate_amendment
    docstring and views.py's _apply_amended_so_lines) depends on submitted lines
    carrying `so_item_id` -- the same identity used to apply an amendment IN
    PLACE rather than delete-and-rebuild (which would silently re-open a
    deliberately closed line). form.html's submit handler serialises it on ONE
    line; deleting that line leaves every existing pytest test green (no test
    drove a real browser submit with an existing item id), because the test
    client posts line_items JSON directly rather than exercising this JS. Pin
    the render so a future edit to that block cannot silently drop the key."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}/amend').data.decode()
    assert re.search(r'so_item_id:\s*item\.so_item_id', html) is not None, (
        'the submit-time line serialiser no longer emits so_item_id -- an '
        'amendment would no longer be able to update existing lines in place')


def test_edit_form_so_number_is_not_read_only(client, db_session, customer, product):
    """Guard the negative direction: the amend_mode readonly branch must not leak
    into the ordinary draft edit form, which still needs so_number editable."""
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '3000', 'unit_price': '4.20', 'amount': '12600.00'}])
    client.post('/sales-orders/create', data={
        'so_number': '2026080004', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60',
        'notes': '', 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='2026080004').one()
    html = client.get(f'/sales-orders/{so.id}/edit').data.decode()
    m = re.search(r'<input[^>]*name="so_number"[^>]*>', html)
    assert m is not None, 'so_number input not found in the edit form'
    assert 'readonly' not in m.group(0)


def test_amend_refuses_removal_of_a_dr_referenced_line_with_the_dr_message(
        client, db_session, branch, customer, product):
    """The companion case: a DR reference with delivered == 0 (draft status,
    not billed) must still get the DR-specific message. This is the FK-orphan
    guard's own reason for existing -- it must still fire once the delivered
    check is checked first. Assert the delivered-line wording is ABSENT."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    soi = so.line_items[0]

    dr = DeliveryReceipt(
        branch_id=branch.id, dr_number='DR-DRAFT-2', delivery_date=date(2026, 8, 4),
        sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
        status='draft')
    dr.line_items.append(DeliveryReceiptItem(
        line_number=1, sales_order_item_id=soi.id, product_id=soi.product_id,
        delivered_quantity=Decimal('0')))
    db_session.add(dr)
    db_session.commit()

    lines = json.dumps([])  # submit with the SO's only line removed
    resp = client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines,
        'amend_reason': 'Attempting to remove a DR-referenced but undelivered line',
        'authorizing_po_number': 'PO-DR-2', 'row_version': str(so.row_version),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'referenced by a Delivery Receipt' in resp.data
    assert b'already delivered. Close the line instead to stop further delivery.' not in resp.data

    db_session.refresh(so)
    assert len(so.line_items) == 1
    assert so.line_items[0].id == soi.id


# --- Task 9: revision banner on both print surfaces -------------------------

def test_print_shows_no_revision_banner_at_rev0(client, db_session, customer, product):
    """Unamended orders must print exactly as they do today."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.id}/print').data.decode()
    assert 'REV.' not in html
    assert 'Supersedes' not in html


def test_print_shows_revision_banner_after_amendment(
        client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20',
                         'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version)}, follow_redirects=True)

    html = client.get(f'/sales-orders/{so.id}/print').data.decode()
    assert 'REV. 1' in html
    assert 'Supersedes Rev. 0' in html


def test_job_order_slip_shows_no_revision_banner_at_rev0(
        client, db_session, customer, product):
    """The production slip is the surface that matters most -- pin the Rev 0
    absence here too, not only on print.html."""
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get(f'/sales-orders/{so.so_number}/print-job-order').data.decode()
    assert 'REV.' not in html
    assert 'Supersedes' not in html


def test_job_order_slip_shows_revision_banner_after_amendment(
        client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version)}, follow_redirects=True)

    # Note: print_job_order is keyed on so_number, not id (views.py:821) -- the
    # route path is also print-job-order, not job-order-print.
    html = client.get(f'/sales-orders/{so.so_number}/print-job-order').data.decode()
    assert 'REV. 1' in html
    assert 'destroy prior copies' in html


def test_list_shows_rev_chip_only_for_amended_orders(
        client, db_session, customer, product):
    so = _confirmed_so(client, db_session, customer, product, Decimal('3000'))
    html = client.get('/sales-orders').data.decode()
    assert 'Rev 1' not in html          # Rev 0 gets no chip
    # A stronger absence check than the one above: 'Rev 1' not in html would
    # stay TRUE even if the chip mistakenly rendered "Rev 0" (RIC's 121
    # pre-existing confirmed orders each carry exactly one Rev 0 row -- see
    # migration sorev_0002) -- so pin the chip's absence by its own class,
    # not merely by the higher revision number's text.
    assert 'so-rev-chip' not in html

    lines = json.dumps([{'line_number': 1, 'product_id': product.id,
                         'quantity': '7000', 'unit_price': '4.20', 'amount': '29400.00'}])
    client.post(f'/sales-orders/{so.id}/amend', data={
        'so_number': '2026080001', 'order_date': '2026-08-04',
        'customer_id': str(customer.id), 'payment_terms': 'Net 60', 'notes': '',
        'line_items': lines, 'amend_reason': 'PO received after job order issued',
        'authorizing_po_number': 'PO-MMS-88421',
        'row_version': str(so.row_version)}, follow_redirects=True)

    html = client.get('/sales-orders').data.decode()
    assert '<span class="so-rev-chip">Rev 1</span>' in html
