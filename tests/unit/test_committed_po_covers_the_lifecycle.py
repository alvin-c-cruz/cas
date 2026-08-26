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
`draft`, which IS in the tuple. There was no submitted-PO case anywhere. Hence
TestEveryLifecycleStatusIsClassified below -- the one-word fix is not the
durable part, the recurrence is.
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


class TestEveryLifecycleStatusIsClassified:
    """THE DURABLE HALF. The one-word fix is not what stops this recurring.

    `submitted` fell through because a status was added to the purchase order's
    lifecycle and nobody revisited a tuple in another module that silently
    enumerates that lifecycle. Nothing failed; the new state was simply invisible.

    This reads the REAL writers out of the source and demands that each one be
    deliberately classified -- either it counts, or it is named here as
    excluded-on-purpose. A status added tomorrow fails this test until somebody
    makes that decision, which is the only thing that generalises.
    """

    #: Statuses that deliberately do NOT consume requisition quantity, with the
    #: reason. Anything not here and not in COMMITTED_PO fails the test below.
    EXCLUDED_ON_PURPOSE = {
        'cancelled': 'a cancelled order releases its lines -- the reason '
                     'allocation is derived and never stored',
    }

    def _statuses_written_by_the_app(self):
        """Every literal assigned to a PurchaseOrder's status, read from source.

        Deliberately source-scraped rather than compared against a hand-kept
        constant: a hand-kept list is the same kind of second enumeration that
        caused this bug, and it would drift the same way.
        """
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[2] / 'app'
        found = set()
        for path in (root / 'purchase_orders' / 'views.py',
                     root / 'purchase_billing.py'):
            for m in re.finditer(r"\bpo\.status\s*=\s*'([a-z_]+)'",
                                 path.read_text(encoding='utf-8')):
                found.add(m.group(1))
        # The column default -- an order's first status is never assigned.
        found.add('draft')
        return found

    def test_the_scraper_finds_the_known_statuses(self):
        """Guard on the guard. If the scrape returns nothing (a refactor renamed
        the variable, the files moved), the real test below would pass
        vacuously against an empty set."""
        found = self._statuses_written_by_the_app()
        assert {'draft', 'submitted', 'approved', 'cancelled'} <= found, found

    def test_every_written_status_is_either_committed_or_excluded(self):
        unclassified = {s for s in self._statuses_written_by_the_app()
                        if s not in COMMITTED_PO
                        and s not in self.EXCLUDED_ON_PURPOSE}
        assert not unclassified, (
            'These PurchaseOrder statuses are written by the app but appear '
            'neither in COMMITTED_PO nor in EXCLUDED_ON_PURPOSE: %s. Decide '
            'whether each one consumes requisition quantity and say so in one '
            'place or the other -- leaving it unclassified is exactly how '
            "'submitted' became invisible to the whole allocation system."
            % sorted(unclassified))
