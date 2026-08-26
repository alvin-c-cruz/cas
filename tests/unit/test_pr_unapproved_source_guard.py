"""Which of a purchase order's SOURCE requisitions are not yet approved.

The predicate behind the owner decision of 2026-08-26: a submitted requisition
may be pulled onto a draft purchase order (staff can prepare the order early),
but that order may not be APPROVED until every requisition feeding it has been.

Deliberately ONE predicate rather than three separate guards on
submitted / rejected / cancelled. Those are the same rule -- "the demand behind
this line was never authorised" -- and three spellings of one rule is how the
three drift apart. It is asked at PO approval, not at pull and not at submit:
pulling is data entry, submitting is a staff purchaser handing the order on, and
approval is the control.

Note APPROVED_PR is NOT `status == 'approved'`. `partially_converted` and
`converted` are POST-approval states -- a requisition reaches them only by having
been approved and then ordered against -- so treating them as unapproved would
block the second purchase order raised against a partially ordered requisition,
which is the ordinary case that partial allocation exists to serve.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.purchase_requests.allocation import APPROVED_PR, unapproved_source_prs
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]


def _pr(db_session, main_branch, admin_user, status, number='SRC-PR-1', lines=1):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 26),
                         branch_id=main_branch.id, status=status,
                         created_by_id=admin_user.id)
    for n in range(1, lines + 1):
        pr.line_items.append(PurchaseRequestItem(
            line_number=n, description='Carbide %d' % n, quantity=20))
    db_session.add(pr)
    db_session.commit()
    return pr


def _po(db_session, main_branch, admin_user, pr_items, status='draft',
        number='SRC-PO-1'):
    """A purchase order whose lines point at *pr_items* (may be empty)."""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 26),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    if pr_items:
        for n, item in enumerate(pr_items, start=1):
            po.line_items.append(PurchaseOrderItem(
                line_number=n, description='Carbide %d' % n, quantity=5,
                unit_price=10, amount=Decimal('50'), source_pr_item_id=item.id))
    else:
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='Loose services', quantity=1,
            unit_price=100, amount=Decimal('100'), source_pr_item_id=None))
    db_session.add(po)
    db_session.commit()
    return po


class TestCleanOrders:
    """Controls. Each of these MUST stay empty -- a guard that fires on an order
    it has no business blocking is worse than no guard, because the way out is
    to delete a legitimate line."""

    def test_a_po_with_no_requisition_source_is_clean(
            self, db_session, main_branch, admin_user):
        """THE control for every client without the requisition module at all.

        A services purchase order is raised straight against a vendor with no
        requisition behind it -- `source_pr_item_id` is NULL on every line. If
        this ever returns anything, the guard has broken the services path and
        every Zhiyuan-shaped install with it.
        """
        po = _po(db_session, main_branch, admin_user, [])
        assert unapproved_source_prs(po) == []

    def test_an_approved_source_is_clean(self, db_session, main_branch, admin_user):
        pr = _pr(db_session, main_branch, admin_user, 'approved')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert unapproved_source_prs(po) == []

    def test_a_partially_converted_source_is_clean(
            self, db_session, main_branch, admin_user):
        """A POST-approval state. A requisition reaches partially_converted only
        by being approved and then ordered against, so the second purchase order
        raised against it must not be blocked -- that is the ordinary case
        partial allocation exists to serve.
        """
        pr = _pr(db_session, main_branch, admin_user, 'partially_converted')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert unapproved_source_prs(po) == []

    def test_a_converted_source_is_clean(self, db_session, main_branch, admin_user):
        pr = _pr(db_session, main_branch, admin_user, 'converted')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert unapproved_source_prs(po) == []


class TestUnapprovedSources:

    def test_a_submitted_source_is_returned(self, db_session, main_branch, admin_user):
        """The case the whole change exists for: staff pulled it before approval."""
        pr = _pr(db_session, main_branch, admin_user, 'submitted')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]

    def test_a_rejected_source_is_returned(self, db_session, main_branch, admin_user):
        """Pulled while submitted, then rejected. Nothing unwinds the PO lines,
        so approval is the only place left to catch it."""
        pr = _pr(db_session, main_branch, admin_user, 'rejected')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]

    def test_a_cancelled_source_is_returned(self, db_session, main_branch, admin_user):
        """Cancelled withdraws the demand. Note a cancelled requisition may
        carry approved_at (cancel() accepts an approved requisition), which is
        exactly why this is decided on STATUS and not on approved_at."""
        pr = _pr(db_session, main_branch, admin_user, 'cancelled')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]

    def test_a_draft_source_is_returned(self, db_session, main_branch, admin_user):
        """The picker never offers a draft, so reaching this needs a hand-posted
        source_pr_item_id -- which is precisely the door the pending-amendment
        bug proved is real (cas 5892bf0a)."""
        pr = _pr(db_session, main_branch, admin_user, 'draft')
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]


class TestShape:

    def test_two_lines_from_one_requisition_return_it_once(
            self, db_session, main_branch, admin_user):
        """A message that names the same requisition twice reads as two problems.

        Pins the RESULT, not the mechanism -- and deliberately so. Deleting the
        query's `.distinct()` leaves this green, because `Query.all()` over a
        single full entity already collapses duplicates through the identity
        map. Two mechanisms guarantee this and neither is observable alone, so
        there is no mutation that isolates one; what a caller depends on is that
        the requisition appears once, which is what this asserts.
        """
        pr = _pr(db_session, main_branch, admin_user, 'submitted', lines=2)
        po = _po(db_session, main_branch, admin_user, pr.line_items)
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]

    def test_only_the_unapproved_source_is_returned(
            self, db_session, main_branch, admin_user):
        """Mixed order: one approved requisition, one submitted. The approved one
        must not appear -- otherwise the refusal names a document that is fine
        and the buyer edits the wrong thing."""
        ok = _pr(db_session, main_branch, admin_user, 'approved', number='SRC-PR-OK')
        bad = _pr(db_session, main_branch, admin_user, 'submitted', number='SRC-PR-BAD')
        po = _po(db_session, main_branch, admin_user,
                 [ok.line_items[0], bad.line_items[0]])
        assert [p.id for p in unapproved_source_prs(po)] == [bad.id]

    def test_results_are_ordered_by_requisition_number(
            self, db_session, main_branch, admin_user):
        """Deterministic, so the refusal message does not reshuffle between
        identical attempts and read as a different problem each time."""
        b = _pr(db_session, main_branch, admin_user, 'submitted', number='SRC-PR-B')
        a = _pr(db_session, main_branch, admin_user, 'submitted', number='SRC-PR-A')
        po = _po(db_session, main_branch, admin_user,
                 [b.line_items[0], a.line_items[0]])
        assert [p.pr_number for p in unapproved_source_prs(po)] == [
            'SRC-PR-A', 'SRC-PR-B']

    def test_a_cancelled_purchase_order_is_still_measured(
            self, db_session, main_branch, admin_user):
        """UNLIKE the allocation sums, this does NOT filter on PO status. The
        question is about THIS order's own lines, not about what quantity is
        spoken for, so COMMITTED_PO has no bearing on it. Pinned because reusing
        that tuple here is the obvious-looking wrong move.
        """
        pr = _pr(db_session, main_branch, admin_user, 'submitted')
        po = _po(db_session, main_branch, admin_user, pr.line_items,
                 status='cancelled')
        assert [p.id for p in unapproved_source_prs(po)] == [pr.id]


class TestApprovedPrTuple:

    def test_approved_pr_names_every_post_approval_state(self):
        """Pins the tuple itself. `partially_converted` and `converted` are the
        two that get dropped by anyone writing `status == 'approved'` from
        memory -- which is how the second PO against a partially ordered
        requisition would start refusing to approve.
        """
        assert set(APPROVED_PR) == {'approved', 'partially_converted', 'converted'}
