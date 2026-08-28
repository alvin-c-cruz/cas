"""Derived allocation arithmetic: how much of a requisition line is on order.

Mirrors receiving_reports.models.po_line_open_qty. Nothing is stored -- the
answer is always a SUM over the PO lines that point at the requisition line,
so a cancelled PO stops counting with no restore step.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.allocation import (
    COMMITTED_PO, pr_line_is_open, pr_line_open_qty, pr_line_ordered_qty)
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]


def _pr_line(db_session, main_branch, admin_user, qty, number='ALLOC-1'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 15),
                         branch_id=main_branch.id, status='approved',
                         created_by_id=admin_user.id)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='Carbide', quantity=qty))
    db_session.add(pr)
    db_session.commit()
    return pr.line_items[0]


def _po_line(db_session, main_branch, admin_user, pr_item, qty, status='draft',
             number='ALLOC-PO-1'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 15),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Carbide', quantity=qty, unit_price=10,
        amount=Decimal(str(qty)) * 10, source_pr_item_id=pr_item.id))
    db_session.add(po)
    db_session.commit()
    return po


class TestOrderedQty:

    def test_nothing_ordered_is_zero(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        assert pr_line_ordered_qty(line) == Decimal('0')

    def test_a_draft_po_counts(self, db_session, main_branch, admin_user):
        """Draft POs count: a line pulled onto a draft is spoken for, so two
        buyers cannot both claim it."""
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 8, status='draft')
        assert pr_line_ordered_qty(line) == Decimal('8')

    def test_a_cancelled_po_does_not_count(self, db_session, main_branch, admin_user):
        """The whole reason for deriving: cancelling reopens the line with no
        restore step."""
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 8, status='cancelled')
        assert pr_line_ordered_qty(line) == Decimal('0')

    def test_exclude_po_id_leaves_that_po_out(self, db_session, main_branch, admin_user):
        """Editing a draft PO must not count its own lines against itself, or
        saving it unchanged fails the ceiling check."""
        line = _pr_line(db_session, main_branch, admin_user, 20)
        po = _po_line(db_session, main_branch, admin_user, line, 8)
        assert pr_line_ordered_qty(line, exclude_po_id=po.id) == Decimal('0')

    def test_several_pos_accumulate(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 8, number='ALLOC-PO-1')
        _po_line(db_session, main_branch, admin_user, line, 5, number='ALLOC-PO-2')
        assert pr_line_ordered_qty(line) == Decimal('13')


class TestOpenQty:

    def test_open_is_requested_minus_ordered(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 8)
        assert pr_line_open_qty(line) == Decimal('12')

    def test_fully_ordered_is_zero(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 20)
        assert pr_line_open_qty(line) == Decimal('0')

    def test_an_unquantified_line_has_no_ceiling(self, db_session, main_branch, admin_user):
        """PurchaseRequest.LINE_QUANTITY_REQUIRED is False -- 'Cement, quantity
        to follow' is a legal line. There is no arithmetic to do."""
        line = _pr_line(db_session, main_branch, admin_user, None)
        assert pr_line_open_qty(line) is None


class TestIsOpen:
    """The predicate the status rules are written over, because quantity
    comparison is meaningless for an unquantified line."""

    def test_untouched_quantified_line_is_open(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        assert pr_line_is_open(line) is True

    def test_partly_ordered_quantified_line_is_open(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 8)
        assert pr_line_is_open(line) is True

    def test_fully_ordered_quantified_line_is_closed(self, db_session, main_branch, admin_user):
        line = _pr_line(db_session, main_branch, admin_user, 20)
        _po_line(db_session, main_branch, admin_user, line, 20)
        assert pr_line_is_open(line) is False

    def test_unquantified_line_closes_on_any_reference(self, db_session, main_branch, admin_user):
        """Boolean, not subtraction."""
        line = _pr_line(db_session, main_branch, admin_user, None)
        assert pr_line_is_open(line) is True
        _po_line(db_session, main_branch, admin_user, line, 3)
        assert pr_line_is_open(line) is False


def test_cancelled_is_the_only_excluded_status():
    """Control on the constant itself -- adding 'cancelled' here would silently
    stop lines reopening.

    The exclusion is the rule; the membership is not. This test used to also
    assert `set(COMMITTED_PO) == {'draft', 'approved', 'partially_received',
    'closed'}`, freezing the tuple's exact contents -- and that snapshot was
    taken while `submitted` was MISSING, so the assertion pinned
    BUG-SUBMITTED-PO-NOT-COUNTED-IN-PR-ALLOCATION in place and went red the
    moment the bug was fixed on 2026-08-26. A test that fails when the codebase
    gets better is pinning the defect, not the rule.

    What replaces it is not another snapshot: see
    tests/unit/test_lifecycle_tuples_are_classified.py, which scrapes the
    purchase order's REAL status writers out of the source and demands each be
    classified -- by COMMITTED_PO and by the nine sibling tuples too. That
    catches a newly added status, which a frozen set never could -- it only ever
    catches someone editing the tuple, which is the safe direction.
    """
    assert 'cancelled' not in COMMITTED_PO
    # The statuses this module's own tests depend on counting.
    assert {'draft', 'submitted', 'approved'} <= set(COMMITTED_PO)
