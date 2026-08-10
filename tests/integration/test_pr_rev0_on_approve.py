"""Approving a Purchase Request writes Rev 0. A refused approval writes nothing."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    """purchase_requests is optional AND depends on purchase_orders -- without
    both, enforce_module_access 404s the route for every role, admin included."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    """Direct-session login. conftest's login_user posts through /login, which
    does not select a branch, so an admin with more than one accessible branch
    is bounced to the picker and the approve POST never lands."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(db_session, branch, status='submitted', number='PR-2026-08-0001',
        lines=(('Cement', '10'),)):
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 8, 10), status=status,
                         reason='Site needs cement')
    for n, (desc, qty) in enumerate(lines, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=desc, quantity=Decimal(qty), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    return pr


def _revs(pr):
    return (DocumentRevision.query
            .filter_by(document_type='purchase_requests', document_id=pr.id)
            .order_by(DocumentRevision.revision_number).all())


class TestRevZeroOnApprove:

    def test_approving_writes_exactly_one_revision_numbered_zero(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch)
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'approved'
        revs = _revs(pr)
        assert len(revs) == 1
        assert revs[0].revision_number == 0

    def test_the_baseline_carries_no_reason(
            self, client, accountant_user, main_branch, db_session):
        # write_revision RAISES if a baseline is given a reason -- the panel keys
        # on "a reason means an amendment", so a Rev 0 with one would render as
        # an amendment numbered zero.
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch)
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert _revs(pr)[0].reason is None

    def test_the_snapshot_records_the_pr_as_APPROVED_not_as_submitted(
            self, client, accountant_user, main_branch, db_session):
        # Written AFTER the status assignment on purpose: Rev 0 is "the PR as
        # approved". Capturing it before would record the pre-approval state and
        # then caption it as the approved original.
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch)
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        snap = json.loads(_revs(pr)[0].snapshot_json)
        assert snap['header']['status'] == 'approved'
        assert snap['header']['approved_by_id'] == str(accountant_user.id)

    def test_the_snapshot_carries_the_lines(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, lines=(('Cement', '10'), ('Sand', '4')))
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        snap = json.loads(_revs(pr)[0].snapshot_json)
        assert [row['description'] for row in snap['lines']] == ['Cement', 'Sand']
        assert [row['quantity'] for row in snap['lines']] == ['10', '4']

    def test_the_revision_records_who_and_which_branch(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch)
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        rev = _revs(pr)[0]
        assert rev.amended_by_id == accountant_user.id
        assert rev.branch_id == main_branch.id


class TestRefusedApprovalWritesNothing:
    """Controls. Every guard in approve() must leave no revision behind -- a
    baseline for a document that was never approved is a false record."""

    def test_a_draft_pr_cannot_be_approved_and_leaves_no_revision(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='draft')
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'draft'
        assert _revs(pr) == []

    def test_an_already_approved_pr_is_not_re_baselined(
            self, client, accountant_user, main_branch, db_session):
        _login(client, accountant_user, main_branch)
        pr = _pr(db_session, main_branch, status='approved')
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert _revs(pr) == []

    def test_a_staff_user_cannot_approve_and_leaves_no_revision(
            self, client, staff_user, main_branch, db_session):
        """_approve_gate() is `has_full_access or role == 'accountant'` -- staff
        is excluded, while _pr_role_gate() (used by create/edit) admits staff.
        That divergence is where slice 2's Critical lived on the PO side.

        TWO preconditions, and BOTH were needed to make this test mean anything
        (proven by mutation: with either missing, deleting the role gate outright
        left this test green):

          * the MODULE. conftest's staff_user does not list purchase_requests in
            set_book_permissions, so without an explicit grant the request is
            stopped by module access.
          * a BRANCH. staff_user never calls set_branches() either, so it has
            zero accessible branches and the validate_branch_session
            before_request hook clears the session branch and bounces it to the
            picker -- before any view runs.

        Either one alone stops the request short of the role gate, so the
        assertion "status is still submitted" holds for a reason that has nothing
        to do with authorization.
        """
        staff_user.set_book_permissions({'purchase_requests': True,
                                         'purchase_orders': True, 'products': True})
        staff_user.set_branches([main_branch])
        db_session.commit()
        _login(client, staff_user, main_branch)
        pr = _pr(db_session, main_branch, status='submitted')
        resp = client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        # Positive control: pin the ROLE GATE's own message. Asserting only
        # "status unchanged" cannot tell the gate from a branch-picker bounce or
        # a module 404, and asserting a generic word like "permission" matches
        # the wrong refusal -- _approve_gate() says "Only an approver".
        assert b'select-branch' not in resp.request.path.encode()
        assert b'Only an approver' in resp.data
        db_session.refresh(pr)
        assert pr.status == 'submitted', 'staff must not be able to approve'
        assert _revs(pr) == []
