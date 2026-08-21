"""A requisition with a PENDING amendment request must not be pullable onto a PO.

BUG-PENDING-AMENDMENT-BLOCK-BYPASSED-BY-THE-PO-FORM, owner-reported 2026-08-21.

The owner decision (2026-08-20) is that a pending amendment request BLOCKS
conversion to a Purchase Order. `purchase_requests.convert()` -- the shortcut
button -- enforced it. The PO FORM did not: `open_lines_for_branch` filtered on
branch + PULLABLE_PR status only, and the PO create POST validated the open
QUANTITY without ever asking whether the source requisition may be pulled from.
So the block was in force on the shortcut and absent on the path buyers use.

TWO LAYERS, EACH ITS OWN TEST. Filtering the picker only removes the option; a
hand-posted `source_pr_item_id` must be refused too. This is the same shape the
AP employee-payee fix (cas afa15b8a) proved: neither layer alone is sufficient,
so each gets a mutation that turns exactly one class RED.
"""
import json
from datetime import date

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder
from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.settings import AppSettings
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders,
              pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def _open_gates(db_session, accountant_user, staff_user):
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_requests', 'purchase_orders', 'products'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    for user in (accountant_user, staff_user):
        perms = user.get_book_permissions()
        perms.update({'purchase_requests': True, 'purchase_orders': True,
                      'products': True})
        user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


def _pr(db_session, branch, number, qty=10):
    pr = PurchaseRequest(pr_number=number, branch_id=branch.id,
                         request_date=date(2026, 8, 13), status='approved')
    db_session.add(pr)
    db_session.flush()
    pr.line_items.append(PurchaseRequestItem(
        purchase_request_id=pr.id, line_number=1,
        description='ITEM %s' % number, quantity=qty))
    db_session.commit()
    return pr


def _pending_on(db_session, pr, user):
    req = PurchaseRequestAmendmentRequest(
        purchase_request_id=pr.id, branch_id=pr.branch_id,
        requested_by_id=user.id, request_reason='A perfectly good reason here.',
        status='pending')
    req.set_proposed({'lines': []})
    db_session.add(req)
    db_session.commit()
    return req


@pytest.fixture
def vendor(db_session):
    v = Vendor(code='PBV1', name='Pull Block Vendor',
               check_payee_name='Pull Block Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def _login(client, accountant_user, branch):
    accountant_user.set_branches([branch])
    db.session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    resp = client.post('/login', data={'username': accountant_user.username,
                                       'password': 'accountant123'},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data


# ---------------------------------------------------- layer 1: the picker
def test_the_picker_does_not_offer_a_pending_amendment_requisition(
        client, db_session, accountant_user, staff_user, main_branch):
    blocked = _pr(db_session, main_branch, '00001')
    _pending_on(db_session, blocked, staff_user)
    free = _pr(db_session, main_branch, '00002')
    _login(client, accountant_user, main_branch)

    resp = client.get('/purchase-requests/open-lines')
    assert resp.status_code == 200
    numbers = {line['pr_number'] for line in resp.get_json()['lines']}
    assert '00002' in numbers, 'anti-vacuity: the picker returned nothing at all'
    assert '00001' not in numbers


# ------------------------------------------------- layer 2: the POST guard
def _po_payload(pr_item, qty, vendor, number='PO-0001'):
    return {
        'po_number': number,
        'order_date': date(2026, 8, 21).isoformat(),
        'vendor_id': str(vendor.id),
        'payment_terms': 'Net 30',
        'vat_treatment': 'inclusive',
        'notes': '',
        'line_items': json.dumps([{
            'source_pr_item_id': pr_item.id,
            'description': pr_item.description,
            'quantity': str(qty), 'unit_price': '1', 'amount': str(qty),
        }]),
    }


def test_a_hand_posted_line_from_a_blocked_requisition_is_refused(
        client, db_session, accountant_user, staff_user, main_branch, vendor):
    """The picker guard only removes the option. This is how the block is
    actually enforced."""
    blocked = _pr(db_session, main_branch, '00003')
    _pending_on(db_session, blocked, staff_user)
    _login(client, accountant_user, main_branch)

    client.post('/purchase-orders/create',
                data=_po_payload(blocked.line_items[0], 2, vendor, 'PO-BLOCKED'),
                follow_redirects=True)

    po = PurchaseOrder.query.filter_by(po_number='PO-BLOCKED').first()
    if po is not None:
        pulled = [li.source_pr_item_id for li in po.line_items]
        assert blocked.line_items[0].id not in pulled, (
            'a Purchase Order was created pulling a line from a requisition with '
            'a pending amendment request')


# ------------------------------------------------------------- CONTROLS
def test_control_a_requisition_without_a_request_is_still_pullable(
        client, db_session, accountant_user, main_branch, vendor):
    """Tripwire: if this fails the guard is refusing everything and the denial
    tests above prove nothing."""
    free = _pr(db_session, main_branch, '00004')
    _login(client, accountant_user, main_branch)

    resp = client.get('/purchase-requests/open-lines')
    numbers = {line['pr_number'] for line in resp.get_json()['lines']}
    assert '00004' in numbers

    client.post('/purchase-orders/create',
                data=_po_payload(free.line_items[0], 3, vendor, 'PO-OK'),
                follow_redirects=True)
    po = PurchaseOrder.query.filter_by(po_number='PO-OK').first()
    assert po is not None, 'an unblocked requisition could not be ordered'
    assert free.line_items[0].id in [li.source_pr_item_id for li in po.line_items]


def test_control_a_resolved_request_unblocks_the_requisition(
        client, db_session, accountant_user, staff_user, main_branch):
    """Only PENDING blocks. Approving or rejecting must return the requisition
    to the picker, or resolving a request would brick it forever."""
    pr = _pr(db_session, main_branch, '00005')
    req = _pending_on(db_session, pr, staff_user)
    _login(client, accountant_user, main_branch)

    numbers = {l['pr_number'] for l in client.get('/purchase-requests/open-lines').get_json()['lines']}
    assert '00005' not in numbers, 'setup: it should be blocked while pending'

    req.status = 'rejected'
    db_session.commit()
    numbers = {l['pr_number'] for l in client.get('/purchase-requests/open-lines').get_json()['lines']}
    assert '00005' in numbers, 'a rejected request left the requisition unpullable'


def test_control_open_quantity_maths_is_undisturbed(
        client, db_session, accountant_user, main_branch, vendor):
    """The partial-pull case. PULLABLE_PR includes partially_converted, so a
    requisition can be legitimately half-ordered; the new guard must not perturb
    the open-quantity arithmetic for requisitions that have no pending request."""
    pr = _pr(db_session, main_branch, '00006', qty=10)
    _login(client, accountant_user, main_branch)

    client.post('/purchase-orders/create',
                data=_po_payload(pr.line_items[0], 4, vendor, 'PO-PART'),
                follow_redirects=True)
    assert PurchaseOrder.query.filter_by(po_number='PO-PART').first() is not None

    lines = client.get('/purchase-requests/open-lines').get_json()['lines']
    mine = [l for l in lines if l['pr_number'] == '00006']
    assert mine, 'the partially-ordered requisition vanished from the picker'
    assert mine[0]['open'] == '6', 'open qty should be 10 - 4 = 6, got %r' % mine[0]['open']
