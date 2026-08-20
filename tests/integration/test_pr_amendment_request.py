"""Staff-initiated amendment requests for approved Purchase Requisitions.

THE INVARIANT THIS FILE EXISTS TO PIN: staff may ASK, never WRITE. `amend` is
approver-gated because gating it on the edit rule shipped a Critical on the
Purchase Order side, so every test that grants staff a new capability is paired
with one proving the requisition itself did not move.

Every test issues a REAL request. Asserting on the service alone would never
exercise the route guards, which is where this class of defect actually lives.
"""
import json

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

MODULES = ('purchase_requests', 'purchase_orders', 'products')


@pytest.fixture(autouse=True)
def _open_gates(db_session, staff_user, accountant_user):
    """Both gates for both actors, or the file is vacuous.

    purchase_requests is optional + per_user, so without the instance flag AND a
    book_permissions grant the module gate 404s every route here and each denial
    assertion passes for the wrong reason. The control tests are the tripwire.
    (memory feedback-outer-gate-masks-inner-guard)
    """
    from app.utils.cache_helpers import clear_module_config_cache
    for key in MODULES:
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    for user in (staff_user, accountant_user):
        perms = user.get_book_permissions()
        perms.update({k: True for k in MODULES})
        user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


@pytest.fixture
def approved_pr(db_session, main_branch, staff_user):
    from datetime import date
    pr = PurchaseRequest(pr_number='00001', branch_id=main_branch.id,
                         request_date=date(2026, 8, 13),
                         status='approved', created_by_id=staff_user.id)
    db_session.add(pr)
    db_session.flush()
    pr.line_items.append(PurchaseRequestItem(
        purchase_request_id=pr.id, line_number=1,
        description='FOR BOILER USE', quantity=1))
    db_session.commit()
    return pr


def _login(client, username, password, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    resp = client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data
    return resp


def _login_staff(client, db_session, staff_user, branch):
    staff_user.set_branches([branch])
    db_session.commit()
    return _login(client, 'staff', 'staff123', branch)


def _login_accountant(client, db_session, accountant_user, branch):
    accountant_user.set_branches([branch])
    db_session.commit()
    return _login(client, accountant_user.username, 'accountant123', branch)


def _lines_payload(pr, qty=2, extra=None):
    """The proposal: the existing line at a new qty, plus optional new lines."""
    out = []
    for li in pr.line_items:
        out.append({'pr_item_id': li.id, 'product_id': None,
                    'description': li.description, 'quantity': qty,
                    'uom_id': None, 'uom_text': None})
    out.extend(extra or [])
    return out


def _file_request(client, pr, lines, reason='Wrong quantity encoded, needs two loads.'):
    return client.post('/purchase-requests/%d/request-amendment' % pr.id, data={
        'pr_number': pr.pr_number,
        'request_date': pr.request_date.isoformat() if pr.request_date else '2026-08-13',
        'reason': pr.reason or '',
        'request_reason': reason,
        'line_items': json.dumps(lines),
    }, follow_redirects=True)


# ---------------------------------------------------------------- staff files
def test_staff_can_file_a_request(client, db_session, staff_user, main_branch, approved_pr):
    _login_staff(client, db_session, staff_user, main_branch)
    resp = _file_request(client, approved_pr, _lines_payload(approved_pr))
    assert resp.status_code == 200

    req = PurchaseRequestAmendmentRequest.query.one()
    assert req.status == 'pending'
    assert req.requested_by_id == staff_user.id
    assert req.branch_id == main_branch.id
    assert req.proposed_lines()[0]['quantity'] == 2


def test_filing_does_not_touch_the_requisition(client, db_session, staff_user,
                                               main_branch, approved_pr):
    """The invariant. row_version is the decisive assertion: it increments on
    every real write, so an unchanged value proves nothing was written."""
    before_version = approved_pr.row_version
    before_qty = approved_pr.line_items[0].quantity
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))

    db_session.expire_all()
    pr = db_session.get(PurchaseRequest, approved_pr.id)
    assert pr.row_version == before_version
    assert pr.line_items[0].quantity == before_qty
    assert pr.status == 'approved'
    assert DocumentRevision.query.count() == 0


def test_staff_still_cannot_amend_directly(client, db_session, staff_user,
                                           main_branch, approved_pr):
    """CONTROL for the whole feature: the new route must not have loosened the
    old one."""
    _login_staff(client, db_session, staff_user, main_branch)
    resp = client.get('/purchase-requests/%d/amend' % approved_pr.id,
                      follow_redirects=True)
    assert b'Only an approver' in resp.data


def test_short_reason_is_refused(client, db_session, staff_user, main_branch, approved_pr):
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr), reason='too short')
    assert PurchaseRequestAmendmentRequest.query.count() == 0


def test_second_pending_request_is_refused(client, db_session, staff_user,
                                           main_branch, approved_pr):
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))
    _file_request(client, approved_pr, _lines_payload(approved_pr, qty=5))
    assert PurchaseRequestAmendmentRequest.query.count() == 1


def test_viewer_cannot_file(client, db_session, viewer_user, main_branch, approved_pr):
    viewer_user.add_branch(main_branch)
    from app.users.module_access import default_all_permissions
    viewer_user.set_book_permissions(default_all_permissions())
    db_session.commit()
    _login(client, 'viewer', 'viewer123', main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))
    assert PurchaseRequestAmendmentRequest.query.count() == 0


# ------------------------------------------------------------ approver acts
def _pending(client, db_session, staff_user, accountant_user, branch, pr, lines=None):
    _login_staff(client, db_session, staff_user, branch)
    _file_request(client, pr, lines if lines is not None else _lines_payload(pr))
    req = PurchaseRequestAmendmentRequest.query.one()
    client.get('/logout')
    _login_accountant(client, db_session, accountant_user, branch)
    return req


def test_approve_applies_the_change_and_appends_a_revision(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    resp = client.post('/purchase-requests/amendment-requests/%d/approve' % req.id,
                       follow_redirects=True)
    assert resp.status_code == 200

    db_session.expire_all()
    pr = db_session.get(PurchaseRequest, approved_pr.id)
    assert float(pr.line_items[0].quantity) == 2.0
    assert pr.pr_number == '00001'          # a revision does not renumber
    assert pr.status == 'approved'          # nor re-open the status

    req = db_session.get(PurchaseRequestAmendmentRequest, req.id)
    assert req.status == 'approved'
    assert req.reviewed_by_id == accountant_user.id
    rev = DocumentRevision.query.filter_by(document_type='purchase_requests').all()
    assert rev, 'approving must append a revision'
    assert req.applied_revision_number is not None


def test_approve_carries_the_requesters_reason_onto_the_revision(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """The reason is the audit trail -- losing it would make the revision say a
    change happened without saying why."""
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    client.post('/purchase-requests/amendment-requests/%d/approve' % req.id,
                follow_redirects=True)
    revs = [r for r in DocumentRevision.query.all() if r.reason]
    assert revs, 'no revision carried a reason'
    assert 'Wrong quantity encoded' in revs[0].reason


def test_reject_leaves_the_requisition_untouched(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    before_qty = approved_pr.line_items[0].quantity
    before_version = approved_pr.row_version
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    client.post('/purchase-requests/amendment-requests/%d/reject' % req.id,
                follow_redirects=True)

    db_session.expire_all()
    pr = db_session.get(PurchaseRequest, approved_pr.id)
    assert pr.line_items[0].quantity == before_qty
    assert pr.row_version == before_version
    assert db_session.get(PurchaseRequestAmendmentRequest, req.id).status == 'rejected'
    assert DocumentRevision.query.count() == 0


def test_staff_cannot_approve_their_own_request(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """The hole this whole design exists to avoid."""
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))
    req = PurchaseRequestAmendmentRequest.query.one()

    client.post('/purchase-requests/amendment-requests/%d/approve' % req.id,
                follow_redirects=True)
    db_session.expire_all()
    assert db_session.get(PurchaseRequestAmendmentRequest, req.id).status == 'pending'
    assert float(db_session.get(PurchaseRequest, approved_pr.id)
                 .line_items[0].quantity) == 1.0


def test_add_and_remove_lines_are_supported(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """Owner decision 2026-08-20: staff may add and remove lines, not only edit."""
    added = [{'pr_item_id': None, 'product_id': None, 'description': 'STARTER FUEL',
              'quantity': 3, 'uom_id': None, 'uom_text': 'BUNDLE'}]
    req = _pending(client, db_session, staff_user, accountant_user, main_branch,
                   approved_pr, lines=_lines_payload(approved_pr) + added)
    client.post('/purchase-requests/amendment-requests/%d/approve' % req.id,
                follow_redirects=True)

    db_session.expire_all()
    pr = db_session.get(PurchaseRequest, approved_pr.id)
    descriptions = sorted((li.description or '') for li in pr.line_items)
    assert 'STARTER FUEL' in descriptions
    assert len(pr.line_items) == 2


# ------------------------------------------------------- conversion is blocked
def test_convert_is_blocked_while_a_request_is_pending(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """Owner decision 2026-08-20: disallow conversion rather than invalidate."""
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    resp = client.post('/purchase-requests/%d/convert' % approved_pr.id,
                       follow_redirects=True)
    assert b'amendment request awaiting review' in resp.data

    db_session.expire_all()
    pr = db_session.get(PurchaseRequest, approved_pr.id)
    assert pr.purchase_order_id is None, 'a Purchase Order was created anyway'
    assert pr.status == 'approved'
    assert db_session.get(PurchaseRequestAmendmentRequest, req.id).status == 'pending'


def test_convert_works_once_the_request_is_rejected(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """CONTROL: the block must lift, or rejecting a request bricks the PR."""
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    client.post('/purchase-requests/amendment-requests/%d/reject' % req.id,
                follow_redirects=True)
    resp = client.post('/purchase-requests/%d/convert' % approved_pr.id,
                       follow_redirects=True)
    assert b'amendment request awaiting review' not in resp.data


# ------------------------------------------------------------- branch scoping
def test_request_in_another_branch_is_invisible(
        client, db_session, staff_user, accountant_user, main_branch, branch_manila,
        approved_pr):
    """Set membership, same rule as the 2026-08-20 branch-scope fixes."""
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    accountant_user.set_branches([branch_manila])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_manila.id

    assert client.get('/purchase-requests/amendment-requests/%d' % req.id).status_code == 404
    client.post('/purchase-requests/amendment-requests/%d/approve' % req.id)
    db_session.expire_all()
    assert db_session.get(PurchaseRequestAmendmentRequest, req.id).status == 'pending'


def test_control_own_branch_review_opens(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    """Tripwire: if this 404s the branch test above proves nothing."""
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    resp = client.get('/purchase-requests/amendment-requests/%d' % req.id)
    assert resp.status_code == 200
    assert b'Wrong quantity encoded' in resp.data


# --------------------------------------------------------------- action items
def test_pending_request_appears_in_action_items_and_the_badge(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    from app.dashboard.action_items_service import count_action_items, gather_approval_items
    req = _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)

    items = gather_approval_items(accountant_user)
    mine = [i for i in items if i['type'] == 'PR Amendment']
    assert len(mine) == 1
    assert mine[0]['id'] == '00001'
    assert str(req.id) in mine[0]['reviewUrl']

    # The badge must agree with the list, or it says N while the page shows N+1.
    assert count_action_items(accountant_user, main_branch.id) >= 1


def test_staff_do_not_see_it_in_the_approval_queue(
        client, db_session, staff_user, accountant_user, main_branch, approved_pr):
    from app.dashboard.action_items_service import gather_approval_items
    _pending(client, db_session, staff_user, accountant_user, main_branch, approved_pr)
    assert gather_approval_items(staff_user) == []


def test_service_refuses_a_duplicate_even_when_called_directly(
        client, db_session, staff_user, main_branch, approved_pr):
    """The ROUTE also refuses a duplicate, and it refuses first -- so the route
    test above never reaches the service's own check. Proved by mutation: with
    the service guard removed the route test still passed.

    This exercises the service directly, so the rule holds for any future caller
    (an import, a CLI, a second route) that does not repeat the route's check.
    """
    from app.purchase_requests.amendment_service import (
        AmendmentRequestError, create_request)
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))
    assert PurchaseRequestAmendmentRequest.query.count() == 1

    with pytest.raises(AmendmentRequestError, match='awaiting review'):
        create_request(approved_pr, staff_user, 'Another perfectly valid reason.',
                       _lines_payload(approved_pr, qty=9))


def test_the_form_will_not_even_open_while_a_request_is_pending(
        client, db_session, staff_user, main_branch, approved_pr):
    """What the ROUTE guard uniquely does, and what the POST test above cannot
    see. Removing the route check still refuses the POST -- the service catches
    it -- so only a GET assertion pins that the form is not offered at all.

    Proved by mutation: with the route check removed this test goes RED while
    test_second_pending_request_is_refused stays green.
    """
    _login_staff(client, db_session, staff_user, main_branch)
    _file_request(client, approved_pr, _lines_payload(approved_pr))

    resp = client.get('/purchase-requests/%d/request-amendment' % approved_pr.id,
                      follow_redirects=True)
    assert b'already has an amendment request awaiting review' in resp.data
    assert b'Submit Request' not in resp.data, 'the form was rendered anyway'


def test_diff_does_not_claim_an_untouched_product_was_cleared(db_session, main_branch,
                                                              staff_user, approved_pr):
    """Regression for a defect only the browser gate could see.

    The stored line carries product_name; the SUBMITTED line carries product_id
    and no label. Diffing the raw dicts read every proposed row as "product
    cleared" -- the review screen showed `COAL -> —` on a row whose product had
    not changed. The earlier tests missed it because their payloads were
    description-only.
    """
    from app.products.models import Product
    from app.purchase_requests.amendment_service import current_lines, diff_lines

    product = Product(code='RM0138', name='COAL', is_active=True)
    db_session.add(product)
    db_session.commit()
    approved_pr.line_items[0].product_id = product.id
    db_session.commit()

    # As the form submits it: product_id, no product_name.
    proposed = [{'pr_item_id': approved_pr.line_items[0].id,
                 'product_id': product.id, 'description': 'FOR BOILER USE',
                 'quantity': 2, 'uom_id': None, 'uom_text': None}]

    row = diff_lines(current_lines(approved_pr), proposed)[0]
    assert row['kind'] == 'modified'
    assert 'quantity' in row['changed']
    assert 'product_name' not in row['changed'], \
        'the untouched product was reported as changed'
    assert row['after']['product_name'] == 'COAL'


def test_diff_treats_1_and_1_00_as_the_same_quantity(db_session, staff_user,
                                                     main_branch, approved_pr):
    """Numeric equality, not string equality -- otherwise an untouched line
    round-tripped through the form reads as MODIFIED."""
    from app.purchase_requests.amendment_service import current_lines, diff_lines
    proposed = [{'pr_item_id': approved_pr.line_items[0].id, 'product_id': None,
                 'description': 'FOR BOILER USE', 'quantity': '1.00',
                 'uom_id': None, 'uom_text': None}]
    row = diff_lines(current_lines(approved_pr), proposed)[0]
    assert row['kind'] == 'unchanged', row
