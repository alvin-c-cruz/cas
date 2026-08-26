"""The ceiling rule and the picker payload."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_requests.allocation import (
    PULLABLE_PR, RECOMPUTABLE_PR, assert_within_open_qty, open_lines_for_branch,
    recompute_pr_status)
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]


@pytest.fixture
def pr(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='RULE-1', request_date=date(2026, 8, 15),
                        date_needed=date(2026, 9, 1), branch_id=main_branch.id,
                        status='approved', created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(
        line_number=1, description='Carbide', quantity=20))
    db_session.add(p)
    db_session.commit()
    return p


def _order(db_session, main_branch, admin_user, pr_item, qty, status='draft',
           number='RULE-PO-1'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 15),
                       branch_id=main_branch.id, status=status,
                       vat_treatment='inclusive', created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Carbide', quantity=qty, unit_price=10,
        amount=Decimal(str(qty)) * 10, source_pr_item_id=pr_item.id))
    db_session.add(po)
    db_session.commit()
    return po


class TestTheCeiling:

    def test_within_the_open_qty_is_allowed(self, pr):
        assert assert_within_open_qty(pr.line_items[0], Decimal('20'), 1) is None

    def test_over_the_open_qty_raises(self, pr):
        with pytest.raises(ValueError) as e:
            assert_within_open_qty(pr.line_items[0], Decimal('21'), 3)
        assert 'Line 3' in str(e.value)
        assert '20' in str(e.value)

    def test_the_ceiling_shrinks_as_lines_are_ordered(self, db_session, main_branch,
                                                      admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        assert_within_open_qty(pr.line_items[0], Decimal('12'), 1)
        with pytest.raises(ValueError):
            assert_within_open_qty(pr.line_items[0], Decimal('13'), 1)

    def test_exclude_po_id_restores_the_ceiling(self, db_session, main_branch,
                                                admin_user, pr):
        """Editing a draft PO that already took 8 must still allow 8."""
        po = _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        assert_within_open_qty(pr.line_items[0], Decimal('8'), 1, exclude_po_id=po.id)

    def test_an_unquantified_line_has_no_ceiling(self, db_session, main_branch,
                                                 admin_user):
        p = PurchaseRequest(pr_number='RULE-2', request_date=date(2026, 8, 15),
                            branch_id=main_branch.id, status='approved',
                            created_by_id=admin_user.id)
        p.line_items.append(PurchaseRequestItem(
            line_number=1, description='Cement, qty to follow'))
        db_session.add(p)
        db_session.commit()
        assert assert_within_open_qty(p.line_items[0], Decimal('999'), 1) is None


class TestThePickerPayload:

    def test_it_lists_an_open_line(self, main_branch, pr):
        rows = open_lines_for_branch(main_branch.id)
        assert len(rows) == 1
        assert rows[0]['pr_number'] == 'RULE-1'
        assert rows[0]['requested'] == '20'
        assert rows[0]['ordered'] == '0'
        assert rows[0]['open'] == '20'

    def test_it_carries_date_needed_for_prioritisation(self, main_branch, pr):
        assert open_lines_for_branch(main_branch.id)[0]['date_needed'] == '2026-09-01'

    def test_a_fully_ordered_line_drops_out(self, db_session, main_branch,
                                            admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 20)
        assert open_lines_for_branch(main_branch.id) == []

    def test_a_partly_ordered_line_stays_with_the_remainder(self, db_session,
                                                            main_branch, admin_user, pr):
        _order(db_session, main_branch, admin_user, pr.line_items[0], 8)
        rows = open_lines_for_branch(main_branch.id)
        assert rows[0]['ordered'] == '8'
        assert rows[0]['open'] == '12'

    def test_another_branch_is_not_listed(self, db_session, branch_manila,
                                          admin_user, pr):
        assert open_lines_for_branch(branch_manila.id) == []

    def test_a_draft_requisition_is_not_offered(self, db_session, main_branch, pr):
        """A draft has not been handed to anybody yet -- there is nothing to buy
        against. The line between draft and submitted is the whole of what
        PULLABLE_PR admits (owner decision 2026-08-26)."""
        pr.status = 'draft'
        db_session.commit()
        assert open_lines_for_branch(main_branch.id) == []


class TestWhichStatusesMayBePulled:
    """PULLABLE_PR, one status per test.

    Widened on 2026-08-26 to admit `submitted`, so a staff purchaser can prepare
    the purchase order while the requisition is still with its approver. The
    approval control did not move to the picker -- it moved to PO APPROVAL, via
    unapproved_source_prs(). Pulling is data entry; approving is the control.
    """

    def _statuses(self, db_session, pr, status):
        pr.status = status
        db_session.commit()
        return open_lines_for_branch(pr.branch_id)

    def test_a_submitted_requisition_is_offered(self, db_session, main_branch, pr):
        """THE change. Everything else in this class is a control on it."""
        rows = self._statuses(db_session, pr, 'submitted')
        assert [r['pr_number'] for r in rows] == ['RULE-1']
        assert rows[0]['open'] == '20'

    def test_an_approved_requisition_is_still_offered(self, db_session, main_branch, pr):
        assert len(self._statuses(db_session, pr, 'approved')) == 1

    def test_a_partially_converted_requisition_is_still_offered(
            self, db_session, main_branch, pr):
        assert len(self._statuses(db_session, pr, 'partially_converted')) == 1

    def test_a_rejected_requisition_is_not_offered(self, db_session, main_branch, pr):
        """Widening to `submitted` must not drag its two exits along with it:
        reject() fires FROM submitted, so this is the status the change is most
        likely to leak into."""
        assert self._statuses(db_session, pr, 'rejected') == []

    def test_a_cancelled_requisition_is_not_offered(self, db_session, main_branch, pr):
        assert self._statuses(db_session, pr, 'cancelled') == []

    def test_a_submitted_requisition_under_amendment_is_not_offered(
            self, db_session, main_branch, admin_user, pr):
        """The pending-amendment block must survive the widening.

        This is the guard cas 5892bf0a added after the block proved bypassable
        through the PO form, and it is filtered independently of status
        (`pr_ids_blocked_by_pending_amendment`) precisely because status cannot
        express it. Pinned on a SUBMITTED requisition -- a status that could not
        reach this filter before today -- so the two rules are known to compose
        rather than assumed to.

        Unreachable through the UI at present (AMEND_STATUSES excludes
        `submitted`, so no amendment request can be raised against one), which
        is why the row is written directly. Defence in depth: the filter is
        status-agnostic by design, and this pins that it stays so.
        """
        from app.purchase_requests.amendment_models import (
            PurchaseRequestAmendmentRequest as Req)
        pr.status = 'submitted'
        db_session.add(Req(purchase_request_id=pr.id, branch_id=pr.branch_id,
                           requested_by_id=admin_user.id,
                           request_reason='Quantity was misread off the paper form.',
                           proposed_json='{}', status=Req.STATUS_PENDING))
        db_session.commit()
        assert open_lines_for_branch(main_branch.id) == []


class TestRecomputableExcludesSubmitted:
    """The load-bearing half of the 2026-08-26 widening.

    PULLABLE_PR gained `submitted`; RECOMPUTABLE_PR deliberately did NOT. These
    two tuples now disagree on purpose, which is exactly the kind of asymmetry a
    later reader tidies up -- so it is pinned, with the consequence spelled out.
    """

    def test_recompute_leaves_a_pulled_submitted_requisition_submitted(
            self, db_session, main_branch, admin_user, pr):
        """Behavioural. Fully order a submitted requisition, recompute, and it
        must still be `submitted` -- still approvable, still rejectable."""
        pr.status = 'submitted'
        db_session.commit()
        _order(db_session, main_branch, admin_user, pr.line_items[0], 20)
        assert recompute_pr_status(pr) == 'submitted'
        assert pr.status == 'submitted'

    def test_submitted_is_absent_from_the_tuple(self):
        """Structural, and the one that names the damage.

        If `submitted` is ever added here, a pulled requisition recomputes to
        partially_converted/converted -- and since approve() and reject() both
        require status == 'submitted' exactly, it can then be neither approved
        nor rejected. The approval step disappears with no error anywhere.
        """
        assert 'submitted' not in RECOMPUTABLE_PR

    def test_the_two_tuples_disagree_on_exactly_one_status(self):
        """PULLABLE_PR minus RECOMPUTABLE_PR is {'submitted'} and nothing else.

        Guards the asymmetry from BOTH directions: widening RECOMPUTABLE_PR
        empties this set, and widening PULLABLE_PR any further grows it.
        """
        assert set(PULLABLE_PR) - set(RECOMPUTABLE_PR) == {'submitted'}
