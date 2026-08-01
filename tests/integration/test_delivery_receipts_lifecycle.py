import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, so_line_open_qty

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _confirmed_so(db_session, branch_id):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-C-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=branch_id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    return so


def _create_dr(client, so, soi_id, qty):
    lines = json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': str(qty)}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    return DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()


def _branch(client, branch_id):
    with client.session_transaction() as s:
        s['selected_branch_id'] = branch_id


def test_approve_guard_rejects_over_open_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    dr1 = _create_dr(client, so, soi.id, 4)                       # DR#1 delivers 4
    client.post(f'/delivery-receipts/{dr1.id}/approve', follow_redirects=True)
    db_session.refresh(dr1); assert dr1.status == 'approved'

    dr2 = _create_dr(client, so, soi.id, 7)                       # open is now 6 -> 7 refused
    resp = client.post(f'/delivery-receipts/{dr2.id}/approve', follow_redirects=True)
    db_session.refresh(dr2)
    assert dr2.status == 'draft' and b'exceeds the open quantity' in resp.data

    dr3 = _create_dr(client, so, soi.id, 6)                       # exactly the open qty -> OK
    client.post(f'/delivery-receipts/{dr3.id}/approve', follow_redirects=True)
    db_session.refresh(dr3); assert dr3.status == 'approved'
    assert so_line_open_qty(soi) == Decimal('0')


def test_draft_does_not_consume_open_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    _create_dr(client, so, soi.id, 4)                             # left as draft
    assert so_line_open_qty(soi) == Decimal('10')


def test_cancel_releases_committed_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)
    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    assert so_line_open_qty(soi) == Decimal('6')
    client.post(f'/delivery-receipts/{dr.id}/cancel',
                data={'cancel_reason': 'Customer refused the delivery at the gate.'},
                follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'cancelled' and dr.cancel_reason
    assert so_line_open_qty(soi) == Decimal('10')                 # released


def test_cancel_requires_a_reason(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    resp = client.post(f'/delivery-receipts/{dr.id}/cancel', data={'cancel_reason': 'nope'},
                       follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft' and b'reason' in resp.data


def test_approved_dr_is_locked_for_edit(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)
    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)

    resp = client.post(f'/delivery-receipts/{dr.id}/edit', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-11',
        'lines': json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': '9'}])},
        follow_redirects=True)
    db_session.refresh(dr)
    assert dr.line_items[0].delivered_quantity == Decimal('4')    # unchanged
    assert dr.delivery_date == date(2026, 7, 9)
    assert b'Only a draft Delivery Receipt can be edited' in resp.data


def test_mark_delivered_stamps_actor_and_time(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft'                                   # must be approved first

    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    client.post(f'/delivery-receipts/{dr.id}/deliver', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'delivered'
    assert dr.delivered_by_id == admin_user.id and dr.delivered_at is not None


def test_approve_is_gated_to_accountant_admin(client, db_session, staff_user, admin_user,
                                              main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    # delivery_receipts is per_user + deny-by-default: grant the MODULE so the staff
    # user reaches the approve gate. Otherwise the before_request module gate bounces
    # them first and this test would pass for the wrong reason.
    perms = staff_user.get_book_permissions()
    perms['delivery_receipts'] = True
    staff_user.set_book_permissions(perms)
    staff_user.branches.append(main_branch); db.session.commit()

    _login(client, staff_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, soi.id, 4)                        # staff may create a draft
    assert dr is not None
    resp = client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft'                                   # staff cannot approve
    assert b'approver' in resp.data.lower()
    assert so_line_open_qty(soi) == Decimal('10')                 # nothing committed


def test_billed_dr_cannot_be_cancelled(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user); _branch(client, main_branch.id)
    dr = _create_dr(client, so, so.line_items[0].id, 4)
    dr.status = 'billed'; db.session.commit()                     # sub-project #2 sets this
    resp = client.post(f'/delivery-receipts/{dr.id}/cancel',
                       data={'cancel_reason': 'Trying to cancel an already billed DR.'},
                       follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'billed'
    assert b'billed Delivery Receipt cannot be cancelled' in resp.data


# -- whole-branch-review Finding 3: SO line-close vs. DR-approve re-check -----------------

@pytest.fixture(autouse=True)
def so_module_enabled(db_session):
    """close_line()/cancel() live in the sales_orders blueprint -- enable that module too
    (delivery_receipts is already enabled by dr_enabled above) so this file's cross-module
    tests reach those routes instead of being bounced by the module-disabled gate."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def test_dr_approval_after_so_cancel_shows_misleading_zero_open_qty(
        client, db_session, admin_user, main_branch):
    """The spec's Open Questions section named this explicitly: DR creation/approval
    against a closed SO line 'needs an explicit test, not just an inference from the shared
    helper.' This documents the actual current behavior when an SO's line becomes
    unavailable (here, via cancelling the parent SO) WHILE a draft DR already exists
    against it: so_line_open_qty() returns 0 unconditionally once the parent SO is
    cancelled/closed (regardless of exclude_dr_id), so the DR-approve re-check reports
    'exceeds the open quantity 0' for the stranded draft DR -- a misleading message, since
    nothing was actually over-delivered. This SO-cancel path is intentionally left
    unguarded (only close_line() gets the new guard below, per the review's scoped fix --
    cancelling a whole SO is a separate, header-level action); this test exists to prove
    and pin the current behavior the spec asked to be tested, not to claim it is fixed."""
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    dr = _create_dr(client, so, soi.id, 5)                        # left as draft
    assert dr.status == 'draft'

    client.post(f'/sales-orders/{so.id}/cancel',
               data={'cancel_reason': 'Customer withdrew the order entirely.'},
               follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'cancelled'

    resp = client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'draft'                                   # cannot approve
    assert b'exceeds the open quantity 0' in resp.data             # the misleading message


def test_close_line_refuses_when_a_draft_dr_references_it(client, db_session, admin_user, main_branch):
    """The fix: close_line() must refuse to close a line while a DRAFT DR row still
    references it, instead of silently stranding that DR the way the SO-cancel path above
    does (P-63-style footgun: closed_reason is write-once and there is no un-close route).
    Only a DRAFT DR can be stranded this way -- approve()/edit() are the only call sites that
    re-check open qty via exclude_dr_id, and both refuse anything not 'draft'. Once the
    blocking draft DR is approved or cancelled, the close proceeds normally."""
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    dr = _create_dr(client, so, soi.id, 5)                        # draft DR references the line
    assert dr.status == 'draft'

    resp = client.post(f'/sales-orders/{so.id}/lines/{soi.id}/close',
                       data={'closed_reason': 'customer no longer wants the remainder'},
                       follow_redirects=True)
    db_session.refresh(soi)
    assert soi.line_status == 'open'                               # refused
    assert b'pending (draft) Delivery Receipt' in resp.data

    client.post(f'/delivery-receipts/{dr.id}/cancel',                # clear the blocker
               data={'cancel_reason': 'Customer refused the delivery at the gate.'},
               follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'cancelled'

    resp = client.post(f'/sales-orders/{so.id}/lines/{soi.id}/close',
                       data={'closed_reason': 'customer no longer wants the remainder'},
                       follow_redirects=True)
    db_session.refresh(soi)
    assert soi.line_status == 'closed'                             # now succeeds


def test_close_line_does_not_refuse_when_an_approved_dr_references_it(client, db_session, admin_user, main_branch):
    """Regression test for the Critical finding on 323572d2: short-closing a line after a
    partial delivery is the feature's primary use case (order 10, deliver/approve 5,
    customer waives the rest, close the line so Monitoring stops showing a phantom 5
    undelivered). An APPROVED DR is already committed -- approve()/edit() refuse anything
    not 'draft', so it can never be stranded by closing the line -- and must NOT block the
    close."""
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    dr = _create_dr(client, so, soi.id, 5)                        # DR for 5 of the ordered 10
    assert dr.status == 'draft'
    client.post(f'/delivery-receipts/{dr.id}/approve', follow_redirects=True)
    db_session.refresh(dr)
    assert dr.status == 'approved'

    resp = client.post(f'/sales-orders/{so.id}/lines/{soi.id}/close',
                       data={'closed_reason': 'customer waived the remaining balance'},
                       follow_redirects=True)
    db_session.refresh(soi)
    assert soi.line_status == 'closed'                             # NOT refused -- the fix
    assert b'has been closed' in resp.data


def test_close_line_works_normally_when_no_dr_references_it(client, db_session, admin_user, main_branch):
    """Baseline: a line with NO Delivery Receipt against it at all closes exactly as
    before -- the new guard must not regress the ordinary case."""
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user); _branch(client, main_branch.id)

    resp = client.post(f'/sales-orders/{so.id}/lines/{soi.id}/close',
                       data={'closed_reason': 'no delivery ever attempted'},
                       follow_redirects=True)
    db_session.refresh(soi)
    assert soi.line_status == 'closed'
