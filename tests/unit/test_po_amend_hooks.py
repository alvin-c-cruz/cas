"""consumed_qty counts committed receipts; has_any_child_reference is wider on purpose."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem

pytestmark = [pytest.mark.purchase_orders]


@pytest.fixture
def po(db_session):
    po = PurchaseOrder(po_number='00998', order_date=date(2026, 8, 5), status='approved',
                       vendor_name='ACME', notes='', payment_terms='Net 30',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('10'),
        unit_price=Decimal('5.00'), amount=Decimal('50.00'), line_total=Decimal('50.00'),
        vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.add(po)
    db.session.commit()
    return po


def _rr(po, status, qty):
    rr = ReceivingReport(rr_number='RR-%s' % status, receipt_date=date(2026, 8, 6),
                         purchase_order_id=po.id, vendor_name=po.vendor_name, status=status)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=po.line_items[0].id,
        received_quantity=Decimal(qty)))
    db.session.add(rr)
    db.session.commit()
    return rr


class TestAmendHooks:
    def test_amend_statuses(self):
        assert PurchaseOrder.AMEND_STATUSES == ('approved', 'partially_received')

    def test_consumed_qty_is_zero_with_no_receipts(self, po):
        assert po.consumed_qty(po.line_items[0]) == Decimal('0')

    def test_consumed_qty_counts_an_approved_receipt(self, po):
        _rr(po, 'approved', '4')
        assert po.consumed_qty(po.line_items[0]) == Decimal('4')

    def test_consumed_qty_ignores_a_draft_receipt(self, po):
        _rr(po, 'draft', '4')
        assert po.consumed_qty(po.line_items[0]) == Decimal('0')

    def test_reference_check_sees_a_draft_receipt_the_floor_ignores(self, po):
        # The whole point: wider than the floor. Deleting this line would strand
        # the draft RR's FK and 500 the next open-qty computation.
        _rr(po, 'draft', '4')
        assert po.consumed_qty(po.line_items[0]) == Decimal('0')
        assert po.has_any_child_reference(po.line_items[0]) is True

    def test_reference_check_is_false_when_nothing_references_the_line(self, po):
        assert po.has_any_child_reference(po.line_items[0]) is False

    def test_child_document_label(self):
        assert PurchaseOrder.child_document_label == 'Receiving Report'
