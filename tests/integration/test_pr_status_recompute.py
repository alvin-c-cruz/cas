"""approved -> partially_converted -> converted, recomputed from the lines.

RECOMPUTE-FROM-SOURCE, not increment-and-decrement. The function never reads
its own previous value, so it is idempotent and a status that somehow disagrees
with reality is repaired by running it again.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.allocation import recompute_pr_status
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture
def pr(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='ST-1', request_date=date(2026, 8, 15),
                        branch_id=main_branch.id, status='approved',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='A', quantity=10))
    p.line_items.append(PurchaseRequestItem(line_number=2, description='B', quantity=5))
    db_session.add(p)
    db_session.commit()
    return p


def _order(db_session, main_branch, admin_user, pairs, status='draft', number='ST-PO-1'):
    """pairs: [(pr_item, qty), ...]"""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 15),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    for n, (item, qty) in enumerate(pairs, start=1):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description=item.description, quantity=qty,
            unit_price=1, amount=Decimal(str(qty)), source_pr_item_id=item.id))
    db_session.add(po)
    db_session.commit()
    return po


class TestTheLadder:

    def test_untouched_is_approved(self, pr):
        assert recompute_pr_status(pr) == 'approved'

    def test_partly_ordered_is_partially_converted(self, db_session, main_branch,
                                                   admin_user, pr):
        _order(db_session, main_branch, admin_user, [(pr.line_items[0], 4)])
        assert recompute_pr_status(pr) == 'partially_converted'

    def test_one_line_whole_and_one_untouched_is_still_partial(self, db_session,
                                                               main_branch, admin_user, pr):
        _order(db_session, main_branch, admin_user, [(pr.line_items[0], 10)])
        assert recompute_pr_status(pr) == 'partially_converted'

    def test_everything_ordered_is_converted(self, db_session, main_branch,
                                             admin_user, pr):
        _order(db_session, main_branch, admin_user,
               [(pr.line_items[0], 10), (pr.line_items[1], 5)])
        assert recompute_pr_status(pr) == 'converted'

    def test_it_writes_the_status_to_the_row(self, db_session, main_branch,
                                             admin_user, pr):
        _order(db_session, main_branch, admin_user, [(pr.line_items[0], 4)])
        recompute_pr_status(pr)
        db_session.commit()
        assert db.session.get(PurchaseRequest, pr.id).status == 'partially_converted'


class TestItIsIdempotent:

    def test_running_twice_changes_nothing(self, db_session, main_branch,
                                           admin_user, pr):
        _order(db_session, main_branch, admin_user, [(pr.line_items[0], 4)])
        first = recompute_pr_status(pr)
        second = recompute_pr_status(pr)
        assert first == second == 'partially_converted'

    def test_it_repairs_a_wrong_stored_status(self, db_session, main_branch,
                                              admin_user, pr):
        """Never reads its own previous value -- the property a counter lacks."""
        pr.status = 'converted'
        db_session.commit()
        assert recompute_pr_status(pr) == 'approved'


class TestReopening:

    def test_cancelling_the_po_reopens_the_requisition(self, db_session, main_branch,
                                                       admin_user, pr):
        po = _order(db_session, main_branch, admin_user,
                    [(pr.line_items[0], 10), (pr.line_items[1], 5)])
        assert recompute_pr_status(pr) == 'converted'
        po.status = 'cancelled'
        db_session.commit()
        assert recompute_pr_status(pr) == 'approved'

    def test_removing_a_pulled_line_reopens_it(self, db_session, main_branch,
                                               admin_user, pr):
        po = _order(db_session, main_branch, admin_user, [(pr.line_items[0], 10)])
        assert recompute_pr_status(pr) == 'partially_converted'
        po.line_items.clear()
        db_session.commit()
        assert recompute_pr_status(pr) == 'approved'


class TestTerminalStatusesAreLeftAlone:
    """Control: recompute must not resurrect a cancelled or rejected
    requisition, nor touch a draft."""

    @pytest.mark.parametrize('status', ['draft', 'submitted', 'cancelled', 'rejected'])
    def test_it_does_not_touch(self, db_session, pr, status):
        pr.status = status
        db_session.commit()
        assert recompute_pr_status(pr) == status


class TestIsConverted:

    def test_partly_ordered_is_not_converted(self, db_session, main_branch,
                                             admin_user, pr):
        """The old definition also read purchase_order_id, which the shortcut
        sets even on a partial pull -- that is why it had to change."""
        _order(db_session, main_branch, admin_user, [(pr.line_items[0], 4)])
        pr.purchase_order_id = 999
        db_session.commit()
        assert pr.is_converted() is False

    def test_fully_ordered_is_converted(self, db_session, main_branch, admin_user, pr):
        _order(db_session, main_branch, admin_user,
               [(pr.line_items[0], 10), (pr.line_items[1], 5)])
        assert pr.is_converted() is True


def test_partially_converted_is_amendable():
    assert 'partially_converted' in PurchaseRequest.AMEND_STATUSES


def test_fully_converted_is_not_amendable():
    """Deliberate carry-over of current behaviour -- raise a new requisition
    rather than adding demand to a fully ordered one."""
    assert 'converted' not in PurchaseRequest.AMEND_STATUSES
