"""A requisition's status follows DELIVERY, not just ordering.

Owner request 2026-09-06: "this status must change when the PR is partially or
fully delivered via the RR document". Before this, recompute_pr_status read only
ordered quantity, so a requisition whose goods had physically arrived still read
`converted` -- indistinguishable from one merely on order.

Delivery OUTRANKS ordering: ordering is a promise, receiving is the fact, so a
requisition that is only partly ordered but already partly delivered reads
`partially_received`. `received` is strictly stronger than `converted` -- every
line delivered in full against the REQUESTED quantity.

Chain under test: PR line -> PO line (source_pr_item_id) -> RR line
(purchase_order_item_id). Only RR statuses in COMMITTED_STATUSES count.
"""
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _chain(db_session, branch, requested='10', ordered='10', received=None,
           rr_status='approved', pr_status='approved', number='PRD-1'):
    """Build PR -> PO -> (optional) RR and return the requisition."""
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    from app.vendors.models import Vendor

    vendor = Vendor.query.filter_by(code='PRD-VEND').first()
    if vendor is None:
        vendor = Vendor(code='PRD-VEND', name='Delivery Test Vendor')
        db_session.add(vendor); db_session.commit()

    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status=pr_status,
                         reason='Site needs cement')
    pr_item = PurchaseRequestItem(line_number=1, description='Cement',
                                  quantity=Decimal(requested), uom_text='bag')
    pr.line_items.append(pr_item)
    db_session.add(pr); db_session.commit()

    po = PurchaseOrder(branch_id=branch.id, po_number=f'PO-{number}',
                       order_date=date(2026, 9, 6), status='approved',
                       vendor_id=vendor.id, vendor_name=vendor.name)
    po_item = PurchaseOrderItem(line_number=1, description='Cement',
                                quantity=Decimal(ordered),
                                source_pr_item_id=pr_item.id)
    po.line_items.append(po_item)
    db_session.add(po); db_session.commit()

    if received is not None:
        # An RR is VENDOR-first with no header purchase_order_id: one receipt
        # may span several orders from the same vendor (the multi-PO redesign).
        # The PO link lives on each LINE, via purchase_order_item_id.
        rr = ReceivingReport(branch_id=branch.id, rr_number=f'RR-{number}',
                             receipt_date=date(2026, 9, 6), status=rr_status,
                             vendor_id=vendor.id, vendor_name=vendor.name)
        rr.line_items.append(ReceivingReportItem(
            line_number=1, purchase_order_item_id=po_item.id,
            received_quantity=Decimal(received)))
        db_session.add(rr); db_session.commit()
    return pr


def _recompute(pr, db_session):
    from app.purchase_requests.allocation import recompute_pr_status
    status = recompute_pr_status(pr)
    db_session.commit()
    return status


class TestDeliveryMovesTheStatus:

    def test_fully_ordered_nothing_received_is_converted(self, db_session, main_branch):
        """CONTROL -- the pre-existing behaviour must be unchanged."""
        pr = _chain(db_session, main_branch, number='PRD-CONV')
        assert _recompute(pr, db_session) == 'converted'

    def test_partly_delivered_is_partially_received(self, db_session, main_branch):
        pr = _chain(db_session, main_branch, received='4', number='PRD-PART')
        assert _recompute(pr, db_session) == 'partially_received'

    def test_fully_delivered_is_received(self, db_session, main_branch):
        pr = _chain(db_session, main_branch, received='10', number='PRD-FULL')
        assert _recompute(pr, db_session) == 'received'

    def test_over_delivery_still_counts_as_received(self, db_session, main_branch):
        """>= requested, not == : an over-delivery has certainly satisfied it."""
        pr = _chain(db_session, main_branch, received='12', number='PRD-OVER')
        assert _recompute(pr, db_session) == 'received'


class TestDeliveryOutranksOrdering:

    def test_partly_ordered_and_partly_delivered_reads_received_not_converted(
            self, db_session, main_branch):
        """Requested 10, ordered 6, delivered 3. Ordering alone would say
        partially_converted; delivery is the fact on the ground."""
        pr = _chain(db_session, main_branch, requested='10', ordered='6',
                    received='3', number='PRD-MIX')
        assert _recompute(pr, db_session) == 'partially_received'

    def test_fully_delivered_against_a_partial_order_is_not_received(
            self, db_session, main_branch):
        """Requested 10, ordered 6, all 6 delivered. The REQUISITION asked for
        10 and has had 6, so its question is not yet answered."""
        pr = _chain(db_session, main_branch, requested='10', ordered='6',
                    received='6', number='PRD-SHORT')
        assert _recompute(pr, db_session) == 'partially_received'


class TestOnlyCommittedReceiptsCount:

    @pytest.mark.parametrize('rr_status', ['draft', 'submitted', 'cancelled'])
    def test_an_uncommitted_receipt_delivers_nothing(self, db_session, main_branch,
                                                     rr_status):
        """A draft/submitted/cancelled receipt has delivered nothing. Counting
        it would report a requisition as delivered on the strength of an
        unapproved document."""
        pr = _chain(db_session, main_branch, received='10', rr_status=rr_status,
                    number=f'PRD-{rr_status}')
        assert _recompute(pr, db_session) == 'converted'

    def test_a_billed_receipt_does_count(self, db_session, main_branch):
        pr = _chain(db_session, main_branch, received='10', rr_status='billed',
                    number='PRD-BILLED')
        assert _recompute(pr, db_session) == 'received'


class TestItIsSelfRepairing:

    def test_cancelling_the_receipt_moves_the_status_back(self, db_session,
                                                          main_branch):
        """recompute-from-source: the requisition must fall BACK out of
        received, not stick at its high-water mark."""
        from app.receiving_reports.models import ReceivingReport
        pr = _chain(db_session, main_branch, received='10', number='PRD-BACK')
        assert _recompute(pr, db_session) == 'received'
        rr = ReceivingReport.query.filter_by(rr_number='RR-PRD-BACK').one()
        rr.status = 'cancelled'
        db_session.commit()
        assert _recompute(pr, db_session) == 'converted'


class TestTheRemainderStaysOrderable:

    def test_a_partially_received_pr_is_still_pullable(self):
        """LOAD-BEARING. Delivery outranks ordering, so a partly ordered
        requisition becomes partially_received on its first delivery. If that
        status were not pullable the buyer could never order the remainder."""
        from app.purchase_requests.allocation import PULLABLE_PR
        assert 'partially_received' in PULLABLE_PR
        assert 'received' not in PULLABLE_PR      # nothing left to order

    def test_delivery_states_count_as_approved(self):
        """They are reachable only from post-approval states, so reading them as
        unapproved would block a second order against a part-delivered
        requisition."""
        from app.purchase_requests.allocation import APPROVED_PR
        assert 'partially_received' in APPROVED_PR
        assert 'received' in APPROVED_PR
