"""Is a Sales Order billed? -- derived from its Delivery Receipts, never stored.

`SalesOrder.sales_invoice_id` exists as a column and is read by guards, but NOTHING
in the app ever writes it: the invoicing path sets the flag on the DELIVERY RECEIPT
(`app/sales_invoices/views.py`), not the order. So every "is this SO billed?" check
was permanently False -- most seriously, an invoiced Sales Order could be cancelled.

The column is not merely unwired, it is the wrong SHAPE: one order is routinely
billed by MANY invoices (RIC's real data has orders spanning up to 14), so a single
nullable FK cannot express the answer. Hence a derivation, mirroring how
`so_line_open_qty` already derives delivered quantity rather than storing it.
"""
import pytest
from datetime import date
from decimal import Decimal

from app import db

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _so(db_session, branch, customer, user, number, status='confirmed'):
    from app.sales_orders.models import SalesOrder
    so = SalesOrder(
        branch_id=branch.id, so_number=number, order_date=date(2026, 6, 28),
        customer_id=customer.id, customer_name=customer.name, notes='',
        status=status, subtotal=Decimal('11200.00'), vat_amount=Decimal('1200.00'),
        total_amount=Decimal('11200.00'), created_by_id=user.id,
    )
    db_session.add(so)
    db_session.commit()
    return so


def _dr(db_session, so, branch, customer, number, invoice_id=None, status='delivered'):
    """A Delivery Receipt against `so`. `invoice_id` mirrors what the real invoicing
    path writes (`dr.sales_invoice_id = invoice.id`). A bare id is honest here: the
    derivation reads only whether the column is set, and SQLite FK enforcement is off
    app-wide -- the same shape the sales_invoices route itself produces."""
    from app.delivery_receipts.models import DeliveryReceipt
    dr = DeliveryReceipt(
        branch_id=branch.id, dr_number=number, delivery_date=date(2026, 6, 29),
        sales_order_id=so.id, customer_id=customer.id, customer_name=customer.name,
        status=status, sales_invoice_id=invoice_id,
    )
    db_session.add(dr)
    db_session.commit()
    return dr


# ── the derivation itself ────────────────────────────────────────────────────

def test_an_order_with_no_delivery_receipts_is_not_billed(
        db_session, main_branch, customer, accountant_user):
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-001')
    assert so_is_billed(so) is False


def test_an_order_whose_dr_carries_no_invoice_is_not_billed(
        db_session, main_branch, customer, accountant_user):
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-002')
    _dr(db_session, so, main_branch, customer, 'DR-B-002')
    assert so_is_billed(so) is False


def test_an_order_whose_dr_carries_an_invoice_IS_billed(
        db_session, main_branch, customer, accountant_user):
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-003')
    _dr(db_session, so, main_branch, customer, 'DR-B-003', invoice_id=501)
    assert so_is_billed(so) is True


def test_billed_ness_is_scoped_to_the_order(
        db_session, main_branch, customer, accountant_user):
    """Another order's invoice must not bill this one -- the bug this whole fix is
    about is a billed-check that answers the wrong question."""
    from app.delivery_receipts.models import so_is_billed
    mine = _so(db_session, main_branch, customer, accountant_user, 'SO-B-004')
    other = _so(db_session, main_branch, customer, accountant_user, 'SO-B-005')
    _dr(db_session, other, main_branch, customer, 'DR-B-005', invoice_id=502)
    assert so_is_billed(other) is True
    assert so_is_billed(mine) is False


def test_one_order_billed_by_SEVERAL_invoices_is_billed(
        db_session, main_branch, customer, accountant_user):
    """The reason this is derived rather than stored: an order is routinely billed
    by many invoices (RIC has orders spanning 14), which a single FK cannot hold."""
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-006')
    for i, inv in enumerate((601, 602, 603), start=1):
        _dr(db_session, so, main_branch, customer, 'DR-B-006-%d' % i, invoice_id=inv)
    assert so_is_billed(so) is True


def test_a_cancelled_dr_still_carrying_an_invoice_counts_as_billed(
        db_session, main_branch, customer, accountant_user):
    """Fail CLOSED. Voiding an invoice already clears dr.sales_invoice_id, so the
    flag is the authority; filtering on DR status as well could only ever un-bill an
    order that still points at an invoice, which is the wrong direction for a guard."""
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-007')
    _dr(db_session, so, main_branch, customer, 'DR-B-007',
        invoice_id=701, status='cancelled')
    assert so_is_billed(so) is True


def test_the_legacy_sales_invoice_id_COLUMN_is_ignored(
        db_session, main_branch, customer, accountant_user):
    """The order's own sales_invoice_id must no longer decide anything. It cannot be
    written correctly (one order, many invoices) and nothing in the app sets it, so
    reading it is what produced a guard that never fired. Pinning this stops a future
    change from quietly reinstating the dead column as the source of truth."""
    from app.delivery_receipts.models import so_is_billed
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-008')
    so.sales_invoice_id = 999          # the column no path writes
    db_session.commit()
    assert so_is_billed(so) is False, 'the stored column must not decide billed-ness'


# ── the guard that was dead: cancelling an invoiced order ────────────────────

def test_cancel_is_REFUSED_on_an_order_with_an_invoiced_dr(
        client, db_session, main_branch, customer, accountant_user):
    """The whole point. Before this fix the guard read a never-written column, so an
    invoiced Sales Order could be cancelled outright."""
    from app.sales_orders.models import SalesOrder
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-009')
    _dr(db_session, so, main_branch, customer, 'DR-B-009', invoice_id=901)

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-orders/%d/cancel' % so.id,
                       data={'cancel_reason': 'Customer withdrew the whole order'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b'billed Sales Order cannot be cancelled' in resp.data
    assert db.session.get(SalesOrder, so.id).status == 'confirmed'


def test_cancel_ignores_the_legacy_column_too(
        client, db_session, main_branch, customer, accountant_user):
    """The ROUTE, not just the helper, must stop consulting so.sales_invoice_id.
    Testing this at the helper alone would leave `if so.sales_invoice_id is not None
    or so_is_billed(so)` passing -- the dead column quietly reinstated at the one
    place it did damage."""
    from app.sales_orders.models import SalesOrder
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-011')
    so.sales_invoice_id = 999          # set by nothing in the app; must not block
    db_session.commit()

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-orders/%d/cancel' % so.id,
                       data={'cancel_reason': 'Customer withdrew the whole order'},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(SalesOrder, so.id).status == 'cancelled'


# ── the control itself: no futile Cancel button on a billed order ───────────

def test_detail_page_HIDES_cancel_on_a_billed_order(
        client, db_session, main_branch, customer, accountant_user):
    """The route refuses; the page should not offer the action at all. Asserts the
    cancel URL is gone, not just the label -- the trigger button and the modal's
    own submit share the text 'Cancel Order', so gating only the button would
    leave the modal (and a working POST target) in the DOM while a label-only
    absence test still passed."""
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-012')
    _dr(db_session, so, main_branch, customer, 'DR-B-012', invoice_id=1201)

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/%d' % so.id)
    assert resp.status_code == 200
    assert b'Cancel Order' not in resp.data
    assert ('/sales-orders/%d/cancel' % so.id).encode() not in resp.data
    assert b'cancelModal' not in resp.data
    # positive control on the SAME page -- proves it rendered the real detail
    # view rather than an error/empty body that would pass any absence test.
    assert so.so_number.encode() in resp.data


def test_detail_page_STILL_OFFERS_cancel_on_an_unbilled_order(
        client, db_session, main_branch, customer, accountant_user):
    """The other half: hiding must be scoped to billed orders only."""
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-013')
    _dr(db_session, so, main_branch, customer, 'DR-B-013')   # delivered, uninvoiced

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/sales-orders/%d' % so.id)
    assert resp.status_code == 200
    assert b'Cancel Order' in resp.data
    assert ('/sales-orders/%d/cancel' % so.id).encode() in resp.data
    assert b'cancelModal' in resp.data


def test_hiding_the_button_does_not_replace_the_route_guard(
        client, db_session, main_branch, customer, accountant_user):
    """Belt and braces. The button is gone, but a replayed/hand-made POST must
    still be refused -- a hidden control is not an authorization check."""
    from app.sales_orders.models import SalesOrder
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-014')
    _dr(db_session, so, main_branch, customer, 'DR-B-014', invoice_id=1401)

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-orders/%d/cancel' % so.id,
                       data={'cancel_reason': 'Bypassing the hidden button entirely'},
                       follow_redirects=True)
    assert b'billed Sales Order cannot be cancelled' in resp.data
    assert db.session.get(SalesOrder, so.id).status == 'confirmed'


def test_cancel_still_SUCCEEDS_on_an_unbilled_confirmed_order(
        client, db_session, main_branch, customer, accountant_user):
    """The guard must not over-block: an order with a delivery but no invoice is
    still cancellable, exactly as before."""
    from app.sales_orders.models import SalesOrder
    so = _so(db_session, main_branch, customer, accountant_user, 'SO-B-010')
    _dr(db_session, so, main_branch, customer, 'DR-B-010')   # delivered, not invoiced

    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-orders/%d/cancel' % so.id,
                       data={'cancel_reason': 'Customer withdrew the whole order'},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(SalesOrder, so.id).status == 'cancelled'
