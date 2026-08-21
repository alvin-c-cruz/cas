"""The PR list must show that a requisition has a pending amendment request.

BUG-PR-LIST-NO-PENDING-AMENDMENT-INDICATION, owner-reported 2026-08-21 within a
day of the feature shipping.

WHY IT IS NOT COSMETIC. A pending request BLOCKS conversion to a Purchase Order
(owner decision 2026-08-20). Without an indicator, a buyer scanning the list for
approved requisitions to convert sees an ordinary row, clicks Convert, and only
then meets the refusal -- a blocking state that is knowable at list time was
being withheld until the detail page.

These are RENDER assertions on GET /purchase-requests. A test that only asked the
service "is there a pending request?" would pass against the broken code, because
the defect was that the VIEW never passed the answer to the template.
"""
import pytest
from datetime import date

from sqlalchemy import event

from app import db
from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]

CHIP = b'pending-amendment-chip'


class _TableQueryCounter:
    """Counts statements touching ONE table within the block.

    Deliberately NOT a count of every statement the request issues. That total
    moves for reasons unrelated to this feature -- measured on 2026-08-21, a
    `users` SELECT grew by one between a 1-row and a 7-row list, never touching
    pr_amendment_requests. Asserting on the total would make this test fail on
    unrelated churn, and a test that cries wolf gets loosened until it guards
    nothing. Counting the feature's own table is both narrower and stricter.
    """
    def __init__(self, table):
        self.table = table
        self.count = 0

    def _on_exec(self, conn, cursor, statement, parameters, context, executemany):
        if self.table in statement:
            self.count += 1

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self._on_exec)
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, 'before_cursor_execute', self._on_exec)


@pytest.fixture(autouse=True)
def _open_gates(db_session, accountant_user, staff_user):
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_requests', 'purchase_orders', 'products'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    for user in (accountant_user, staff_user):
        perms = user.get_book_permissions()
        perms.update({'purchase_requests': True, 'purchase_orders': True, 'products': True})
        user.set_book_permissions(perms)
    db_session.commit()
    yield
    clear_module_config_cache()


def _pr(db_session, branch, number, status='approved'):
    pr = PurchaseRequest(pr_number=number, branch_id=branch.id,
                         request_date=date(2026, 8, 13), status=status)
    db_session.add(pr)
    db_session.flush()
    pr.line_items.append(PurchaseRequestItem(purchase_request_id=pr.id, line_number=1,
                                             description='ITEM %s' % number, quantity=1))
    db_session.commit()
    return pr


def _request_on(db_session, pr, user, status='pending'):
    req = PurchaseRequestAmendmentRequest(
        purchase_request_id=pr.id, branch_id=pr.branch_id,
        requested_by_id=user.id, request_reason='A perfectly good reason here.',
        status=status)
    req.set_proposed({'lines': []})
    db_session.add(req)
    db_session.commit()
    return req


def _login(client, accountant_user, branch):
    accountant_user.set_branches([branch])
    db.session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    resp = client.post('/login', data={'username': accountant_user.username,
                                       'password': 'accountant123'},
                       follow_redirects=True)
    assert b'Invalid username or password' not in resp.data


def test_list_marks_a_requisition_with_a_pending_request(
        client, db_session, accountant_user, staff_user, main_branch):
    pr = _pr(db_session, main_branch, '00001')
    _request_on(db_session, pr, staff_user)
    _login(client, accountant_user, main_branch)

    resp = client.get('/purchase-requests')
    assert resp.status_code == 200
    assert b'00001' in resp.data, 'anti-vacuity: the row did not render at all'
    assert CHIP in resp.data


def test_list_does_not_mark_a_requisition_without_one(
        client, db_session, accountant_user, main_branch):
    """CONTROL: the chip is per-row, not painted on every list."""
    _pr(db_session, main_branch, '00002')
    _login(client, accountant_user, main_branch)

    resp = client.get('/purchase-requests')
    assert resp.status_code == 200
    assert b'00002' in resp.data, 'anti-vacuity: the row did not render at all'
    assert CHIP not in resp.data


def test_a_resolved_request_does_not_keep_marking_the_row(
        client, db_session, accountant_user, staff_user, main_branch):
    """CONTROL: only PENDING blocks conversion, so only pending marks the row.
    An approved or rejected request must leave the list clean."""
    for number, status in (('00003', 'approved'), ('00004', 'rejected')):
        pr = _pr(db_session, main_branch, number)
        _request_on(db_session, pr, staff_user, status=status)
    _login(client, accountant_user, main_branch)

    resp = client.get('/purchase-requests')
    assert resp.status_code == 200
    assert b'00003' in resp.data and b'00004' in resp.data
    assert CHIP not in resp.data


def test_the_indicator_costs_one_query_no_matter_how_many_rows(
        client, db_session, accountant_user, staff_user, main_branch):
    """The list paginates at 50. Resolving the pending set per ROW would put 50
    statements on a full page, so the lookup must be exactly ONE regardless of
    how many requisitions are shown -- and exactly one, not "few": zero would
    mean the chip stopped being resolved at all."""
    pr = _pr(db_session, main_branch, '00010')
    _request_on(db_session, pr, staff_user)
    _login(client, accountant_user, main_branch)

    with _TableQueryCounter('pr_amendment_requests') as qc1:
        client.get('/purchase-requests')
    one_row = qc1.count

    for n in range(11, 17):
        extra = _pr(db_session, main_branch, '000%d' % n)
        _request_on(db_session, extra, staff_user)
    with _TableQueryCounter('pr_amendment_requests') as qc7:
        resp = client.get('/purchase-requests')
    seven_rows = qc7.count

    assert b'00016' in resp.data, 'anti-vacuity: the extra rows did not render'
    assert resp.data.count(CHIP) == 7, 'all seven rows should carry the chip'

    # TWO statements, not one, and both are accounted for:
    #   1. `inject_action_items_count` -- a context processor that runs on EVERY
    #      authenticated page and counts pending requests for the sidebar badge;
    #   2. this list's own chip lookup.
    # Neither scales with rows, which is the property that matters. Pinned at an
    # exact number rather than "<= something" so that a regression to a per-row
    # lookup (which would read 1 + 7 = 8 here) fails loudly instead of sliding
    # under a loose bound.
    assert one_row == 2, 'expected 2 amendment queries (badge + chip), got %d' % one_row
    assert seven_rows == one_row, (
        'N+1: %d statements hit pr_amendment_requests for 7 requisitions vs %d for '
        '1 -- the lookup is running per row' % (seven_rows, one_row))
