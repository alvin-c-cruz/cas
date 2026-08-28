"""A SUBMITTED purchase order's lines count against the requisition line.

BUG-SUBMITTED-PO-NOT-COUNTED-IN-PR-ALLOCATION, found live 2026-08-26 during the
Task 7 browser pass and pre-existing on main.

COMMITTED_PO is the ONLY thing that decides whether a purchase-order line is
"spoken for". It is read by exactly two functions -- pr_line_ordered_qty and
_has_committed_reference -- and everything else derives from those: the picker
(open_lines_for_branch), the save-time ceiling (assert_payload_within_open_qty),
and recompute_pr_status. So a status missing from that tuple is invisible to the
whole allocation system at once, on BOTH doors, which is why the two-door guard
from cas 5892bf0a did not help: both doors read the same wrong input.

`submitted` was missing. It arrived with the PO submit step (cas 579e12ed) and
the tuple, written when draft -> approved was the entire lifecycle, was never
widened. A requisition line fully ordered on a submitted order was offered again
at its full original quantity.

The suite could not see it: every allocation test built its purchase order as
`draft`, which IS in the tuple. There was no submitted-PO case anywhere.

THE DURABLE HALF NOW LIVES IN test_lifecycle_tuples_are_classified.py. This
file kept a TestEveryLifecycleStatusIsClassified class that source-scraped the
purchase order's lifecycle and demanded COMMITTED_PO classify every status in
it. That guard was generalised over all ten purchase-area status tuples
(backlog 304) and MOVED rather than copied: two classifiers over one lifecycle
would be a second enumeration to drift, which is the exact defect being
guarded against.

What remains here is the bug's own regression -- the five behaviours a
submitted order must show and the three the whitelist must still refuse.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.purchase_requests.allocation import (
    COMMITTED_PO, assert_payload_within_open_qty, open_lines_for_branch,
    pr_line_is_open, pr_line_open_qty, pr_line_ordered_qty)
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]


@pytest.fixture
def pr_line(db_session, main_branch, admin_user):
    pr = PurchaseRequest(pr_number='CMT-PR-1', request_date=date(2026, 8, 26),
                         branch_id=main_branch.id, status='approved',
                         created_by_id=admin_user.id)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Rebar 10mm', quantity=Decimal('10')))
    db_session.add(pr); db_session.commit()
    return pr.line_items[0]


def _order(db_session, main_branch, admin_user, pr_item, qty, status,
           number='CMT-PO-1'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 26),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Rebar 10mm', quantity=Decimal(str(qty)),
        unit_price=10, amount=Decimal(str(qty)) * 10,
        source_pr_item_id=pr_item.id))
    db_session.add(po); db_session.commit()
    return po


class TestASubmittedOrderCounts:
    """The four questions the picker and the ceiling actually ask."""

    def test_ordered_qty_counts_a_submitted_order(self, db_session, main_branch,
                                                  admin_user, pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 10, 'submitted')
        assert pr_line_ordered_qty(pr_line) == Decimal('10')

    def test_open_qty_drops_to_zero(self, db_session, main_branch, admin_user, pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 10, 'submitted')
        assert pr_line_open_qty(pr_line) == Decimal('0')

    def test_a_fully_ordered_line_is_not_open(self, db_session, main_branch,
                                              admin_user, pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 10, 'submitted')
        assert pr_line_is_open(pr_line) is False

    def test_the_picker_stops_offering_it(self, db_session, main_branch,
                                          admin_user, pr_line):
        """THE reproduction, at the layer the browser exercised: the line was
        offered again at its full original quantity."""
        _order(db_session, main_branch, admin_user, pr_line, 10, 'submitted')
        assert open_lines_for_branch(main_branch.id) == []

    def test_the_save_time_ceiling_refuses_a_second_order(
            self, db_session, main_branch, admin_user, pr_line):
        """The picker is a convenience; THIS is the guard. Both were blind, and
        for one reason -- the ceiling derives from the same tuple."""
        _order(db_session, main_branch, admin_user, pr_line, 10, 'submitted')
        with pytest.raises(ValueError) as e:
            assert_payload_within_open_qty([(pr_line, Decimal('10'), 1)])
        assert 'remain unordered' in str(e.value)

    def test_a_partly_submitted_line_keeps_only_its_remainder(
            self, db_session, main_branch, admin_user, pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 4, 'submitted')
        rows = open_lines_for_branch(main_branch.id)
        assert len(rows) == 1
        assert rows[0]['ordered'] == '4'
        assert rows[0]['open'] == '6'


class TestTheWhitelistStillExcludes:
    """Controls. COMMITTED_PO is a whitelist for a reason -- widening it must not
    turn it into "every status counts"."""

    def test_a_cancelled_order_still_does_not_count(self, db_session, main_branch,
                                                    admin_user, pr_line):
        """The whole reason allocation is DERIVED rather than stored: cancelling
        reopens the line with no restore step."""
        _order(db_session, main_branch, admin_user, pr_line, 10, 'cancelled')
        assert pr_line_ordered_qty(pr_line) == Decimal('0')
        assert len(open_lines_for_branch(main_branch.id)) == 1

    def test_a_draft_order_still_counts(self, db_session, main_branch, admin_user,
                                        pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 10, 'draft')
        assert pr_line_ordered_qty(pr_line) == Decimal('10')

    def test_an_approved_order_still_counts(self, db_session, main_branch,
                                            admin_user, pr_line):
        _order(db_session, main_branch, admin_user, pr_line, 10, 'approved')
        assert pr_line_ordered_qty(pr_line) == Decimal('10')
