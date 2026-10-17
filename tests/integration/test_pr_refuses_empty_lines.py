"""A requisition may not be saved, submitted or approved with no lines.

FOUND live 2026-10-16 (Philgen PR 01021, BUG-PR-DRAFT-EDIT-SAVES-WITH-NO-LINES).
The requester saved two lines, landed on the draft edit page, clicked Update, and
the requisition was saved with none: "updated", then submitted, empty. The rows
were hard-deleted; nothing could be recovered.

Three holes lined up:

  * edit() hands the posted lines to _apply_amended_pr_lines, which deletes every
    stored line absent from the payload and -- deliberately -- enforces no
    minimum: its own comment says the ROUTE must judge the applied result with
    has_requested_line(). amend() does; edit() never did. create() refuses an
    empty requisition and so does amend(); only the draft edit let one through.
  * The form's hidden line field started as value="[]". The submit serialiser
    overwrites it, but only once the script at the very bottom of the page has
    run -- and that script waits for the whole product list. An Update clicked
    while the page is still loading posts "[]", which reads exactly like "the
    user deleted every row". Reproduced in a browser on a copy of the 16 Oct
    books (2026-10-17): 2 lines -> 0, flashed "updated".
  * submit() and approve() checked nothing, so the empty requisition moved on.

The field now starts empty, and an empty or absent field is refused as "did not
reach the server" -- on edit, and on the two amendment screens that share the
template -- with the STORED lines put back on screen.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.amendments.models import DocumentRevision
from app.audit.models import AuditLog
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

STORED = 'Portland Cement Type 1'


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _pr(db_session, branch, number, status='draft', lines=((STORED, '10'),)):
    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 10, 16), status=status,
                         reason='Site needs cement')
    for n, (desc, qty) in enumerate(lines, start=1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description=desc, quantity=Decimal(qty)))
    db_session.add(pr); db_session.commit()
    return pr


def _edit(client, pr, line_items=None, omit_line_items=False):
    data = {
        'request_date': '2026-10-16',
        'reason': 'Re-specified',
        'pr_number': pr.pr_number,
        'row_version': pr.row_version,
    }
    if not omit_line_items:
        data['line_items'] = line_items
    return client.post(f'/purchase-requests/{pr.id}/edit', data=data,
                       follow_redirects=True)


def _actions_for(pr):
    return [a.action for a in AuditLog.query.filter_by(
        module='purchase_requests', record_id=pr.id).all()]


def _hidden_line_field(html):
    tag = re.search(r'<input[^>]*id="prLinesJson"[^>]*>', html)
    assert tag, 'the form must carry the hidden line field'
    return tag.group(0)


class TestAnUpdateMustLeaveALine:

    def test_an_update_with_no_lines_is_refused(self, client, accountant_user,
                                                main_branch, db_session):
        """THE regression -- PR 01021's Update, as the server received it."""
        pr = _pr(db_session, main_branch, 'EMPTY-EDIT-1')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, '[]')
        assert resp.status_code == 200
        assert b'must keep at least one item' in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]
        assert 'update' not in _actions_for(pr)

    def test_an_update_with_only_blank_rows_is_refused(self, client, accountant_user,
                                                       main_branch, db_session):
        """Blank rows are skipped as trailing lines, so they keep nothing either."""
        pr = _pr(db_session, main_branch, 'EMPTY-EDIT-2')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, json.dumps([
            {}, {'product_id': None, 'description': None, 'quantity': None}]))
        assert b'must keep at least one item' in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]

    def test_a_refused_update_writes_nothing_else(self, client, accountant_user,
                                                  main_branch, db_session):
        """The header change rides in the same request; the rollback must take it
        AND claim_version's row_version bump, or the user's next save
        false-conflicts against their own stale token."""
        pr = _pr(db_session, main_branch, 'EMPTY-EDIT-3')
        version = pr.row_version
        _login(client, accountant_user, main_branch)
        _edit(client, pr, '[]')
        db_session.refresh(pr)
        assert pr.reason == 'Site needs cement'
        assert pr.row_version == version


class TestLinesThatNeverReachedTheServer:

    def test_a_blank_line_field_is_refused_and_says_so(self, client, accountant_user,
                                                       main_branch, db_session):
        """What the form now posts when Update is clicked before its script ran.
        Pin the MESSAGE: the minimum-line rule would refuse it too, and blame the
        user for deleting rows they never touched."""
        pr = _pr(db_session, main_branch, 'NOARRIVE-1')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, '')
        assert b'did not reach the server' in resp.data
        assert b'must keep at least one item' not in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]
        assert 'update' not in _actions_for(pr)

    def test_an_absent_line_field_is_refused_and_says_so(self, client, accountant_user,
                                                         main_branch, db_session):
        pr = _pr(db_session, main_branch, 'NOARRIVE-2')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, omit_line_items=True)
        assert b'did not reach the server' in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]

    @pytest.mark.parametrize('raw', ['{not json', '[1,2', '123', '"a string"', 'null'])
    def test_an_unreadable_line_field_is_refused_without_a_500(
            self, client, accountant_user, main_branch, db_session, raw):
        pr = _pr(db_session, main_branch, 'NOARRIVE-3')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, raw)
        assert resp.status_code == 200
        assert b'could not be read' in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]

    def test_the_refusal_puts_the_stored_lines_back_on_screen(
            self, client, accountant_user, main_branch, db_session):
        """Re-rendering the posted payload would show an empty grid -- the very
        picture that invites the next empty Update."""
        pr = _pr(db_session, main_branch, 'NOARRIVE-4')
        _login(client, accountant_user, main_branch)
        resp = _edit(client, pr, '')
        assert STORED.encode() in resp.data


class TestTheFormStartsWithoutAPayload:
    """The serialiser's starting value must not be a valid "no lines" payload."""

    def test_on_the_edit_page(self, client, accountant_user, main_branch, db_session):
        pr = _pr(db_session, main_branch, 'HIDDEN-1')
        _login(client, accountant_user, main_branch)
        tag = _hidden_line_field(
            client.get(f'/purchase-requests/{pr.id}/edit').get_data(as_text=True))
        assert 'value=""' in tag and '[]' not in tag

    def test_on_the_create_page(self, client, accountant_user, main_branch):
        _login(client, accountant_user, main_branch)
        tag = _hidden_line_field(
            client.get('/purchase-requests/create').get_data(as_text=True))
        assert 'value=""' in tag and '[]' not in tag


class TestSubmitNeedsALine:

    def test_submitting_with_no_lines_is_refused(self, client, accountant_user,
                                                 main_branch, db_session):
        """PR 01021 was submitted 41 s after it was emptied."""
        pr = _pr(db_session, main_branch, 'EMPTY-SUBMIT-1', lines=())
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/submit', follow_redirects=True)
        assert b'needs at least one item' in resp.data
        db_session.refresh(pr)
        assert pr.status == 'draft'
        assert 'submit' not in _actions_for(pr)

    def test_submitting_with_a_line_still_works(self, client, accountant_user,
                                                main_branch, db_session):
        """CONTROL -- the guard must refuse only the empty requisition."""
        pr = _pr(db_session, main_branch, 'EMPTY-SUBMIT-2')
        _login(client, accountant_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/submit', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'submitted'


class TestApproveNeedsALine:
    """PR 01021 is live and submitted with no lines. Nothing stopped it being
    approved, and approval writes Rev 0 -- the baseline every amendment is
    measured against -- as an empty requisition."""

    def test_approving_with_no_lines_is_refused(self, client, accountant_user,
                                                main_branch, db_session):
        pr = _pr(db_session, main_branch, 'EMPTY-APPROVE-1', status='submitted',
                 lines=())
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        assert b'needs at least one item' in resp.data
        db_session.refresh(pr)
        assert pr.status == 'submitted'
        assert DocumentRevision.query.filter_by(
            document_type='purchase_requests', document_id=pr.id).count() == 0

    def test_approving_with_a_line_still_works(self, client, accountant_user,
                                               main_branch, db_session):
        """CONTROL."""
        pr = _pr(db_session, main_branch, 'EMPTY-APPROVE-2', status='submitted')
        _login(client, accountant_user, main_branch)
        client.post(f'/purchase-requests/{pr.id}/approve', follow_redirects=True)
        db_session.refresh(pr)
        assert pr.status == 'approved'


class TestTheAmendmentScreensReadABlankFieldTheSameWay:
    """They share the template, so they now receive "" where they used to
    receive "[]". Each must say the lines did not arrive, not judge "" as an
    empty proposal."""

    def test_amend(self, client, accountant_user, main_branch, db_session):
        pr = _pr(db_session, main_branch, 'BLANK-AMEND-1', status='approved')
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/amend', data={
            'pr_number': pr.pr_number, 'request_date': '2026-10-16',
            'reason': 'Site needs cement',
            'amend_reason': 'quantity corrected after site re-measure',
            'row_version': str(pr.row_version), 'line_items': '',
        }, follow_redirects=True)
        assert b'did not reach the server' in resp.data
        db_session.refresh(pr)
        assert [li.description for li in pr.line_items] == [STORED]

    def test_request_amendment(self, client, accountant_user, main_branch, db_session):
        from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
        pr = _pr(db_session, main_branch, 'BLANK-REQ-1', status='approved')
        _login(client, accountant_user, main_branch)
        resp = client.post(f'/purchase-requests/{pr.id}/request-amendment', data={
            'pr_number': pr.pr_number, 'request_date': '2026-10-16',
            'reason': 'Site needs cement',
            'request_reason': 'Wrong quantity encoded, needs two loads.',
            'line_items': '',
        }, follow_redirects=True)
        assert b'did not reach the server' in resp.data
        assert PurchaseRequestAmendmentRequest.query.filter_by(
            purchase_request_id=pr.id).count() == 0
