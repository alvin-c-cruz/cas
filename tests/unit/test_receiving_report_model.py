"""Unit tests for ReceivingReport -- receipts against a Purchase Order (mirror of DeliveryReceipt).
Operational: posts no JE in v1 (journal_entry_id is an inert accrual seam)."""
from decimal import Decimal
from datetime import date

# Module-level import so the model is registered in db.metadata before any
# db_session create_all() runs (app-factory registration lands in Task 2).
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem  # noqa: F401
import pytest

pytestmark = [pytest.mark.receiving_reports]


def _po_with_line(db_session, qty=100, status='approved'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem, generate_po_number
    po = PurchaseOrder(po_number=generate_po_number(), order_date=date(2026, 7, 11),
                       status=status, vat_treatment='inclusive', vendor_name='Acme')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    db_session.add(po); db_session.commit()
    return po


def test_generate_rr_number_increments(db_session):
    from app.receiving_reports.models import ReceivingReport, generate_rr_number
    n1 = generate_rr_number()
    assert n1 == '00001'
    rr = ReceivingReport(rr_number=n1, receipt_date=date(2026, 7, 11), vendor_id=1,
                         vendor_name='Acme', status='draft')
    db_session.add(rr); db_session.commit()
    assert generate_rr_number() == '00002'


def test_generate_rr_number_continues_from_legacy_literal_number(db_session):
    from app.receiving_reports.models import ReceivingReport, generate_rr_number
    rr = ReceivingReport(rr_number='19240', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='draft')
    db_session.add(rr); db_session.commit()
    assert generate_rr_number() == '19241'


def test_generate_rr_number_ignores_legacy_prefixed_numbers(db_session):
    from app.receiving_reports.models import ReceivingReport, generate_rr_number
    rr = ReceivingReport(rr_number='RR-2026-07-0030', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='draft')
    db_session.add(rr); db_session.commit()
    assert generate_rr_number() == '00001'


def test_committed_statuses(db_session):
    from app.receiving_reports.models import COMMITTED_STATUSES
    assert COMMITTED_STATUSES == ('approved', 'billed')


def test_journal_entry_seam_defaults_none(db_session):
    """RR carries an inert journal_entry_id accrual seam (unused in v1)."""
    from app.receiving_reports.models import ReceivingReport
    rr = ReceivingReport(rr_number='RR-2026-07-0001', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='draft')
    assert rr.journal_entry_id is None
    assert rr.accounts_payable_id is None


def test_po_line_open_qty_full(db_session):
    from app.receiving_reports.models import po_line_open_qty
    po = _po_with_line(db_session, qty=100)
    assert po_line_open_qty(po.line_items[0]) == Decimal('100')     # nothing received yet


def test_po_line_open_qty_after_partial_receipt(db_session):
    from app.receiving_reports.models import (
        ReceivingReport, ReceivingReportItem, po_line_open_qty)
    po = _po_with_line(db_session, qty=100)
    poi = po.line_items[0]
    rr = ReceivingReport(rr_number='RR-2026-07-0001', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='approved')
    rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                             received_quantity=Decimal('60')))
    db_session.add(rr); db_session.commit()
    assert po_line_open_qty(poi) == Decimal('40')                    # 100 ordered - 60 received


def test_draft_receipt_does_not_consume_open_qty(db_session):
    from app.receiving_reports.models import (
        ReceivingReport, ReceivingReportItem, po_line_open_qty)
    po = _po_with_line(db_session, qty=100)
    poi = po.line_items[0]
    rr = ReceivingReport(rr_number='RR-2026-07-0002', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='draft')
    rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                             received_quantity=Decimal('60')))
    db_session.add(rr); db_session.commit()
    assert po_line_open_qty(poi) == Decimal('100')                  # draft does not commit


def test_rr_item_delegates_uom_and_price_to_po_line(db_session):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    po = _po_with_line(db_session, qty=100)
    poi = po.line_items[0]
    rr = ReceivingReport(rr_number='RR-2026-07-0003', receipt_date=date(2026, 7, 11),
                         vendor_id=1, vendor_name='Acme', status='draft')
    li = ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                             received_quantity=Decimal('5'))
    rr.line_items.append(li)
    db_session.add(rr); db_session.commit()
    assert li.quantity == Decimal('5')                              # quantity == received_quantity
    d = li.to_dict()
    assert d['received_quantity'] == 5.0 and d['ordered_quantity'] == 100.0


def test_item_has_stock_movement_id_column(db_session):
    from app.receiving_reports.models import ReceivingReportItem
    col = ReceivingReportItem.__table__.columns.get('stock_movement_id')
    assert col is not None
    assert col.nullable is True


class TestPoNumberProperty:
    """`po_number` is derived through purchase_order_item -> order (the PO
    header's backref, NOT `purchase_order` -- see PurchaseOrderItem.order,
    purchase_orders/models.py:107). One receipt may settle several of a vendor's
    orders (Task 4), so this is a per-LINE property, not a header field."""

    def test_po_number_derives_through_the_po_line_and_its_order(self, db_session):
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        po = _po_with_line(db_session, qty=100)
        poi = po.line_items[0]
        rr = ReceivingReport(rr_number='RR-2026-07-0004', receipt_date=date(2026, 7, 11),
                             vendor_id=1, vendor_name='Acme', status='draft')
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                 received_quantity=Decimal('5'))
        rr.line_items.append(li)
        db_session.add(rr)
        db_session.commit()
        assert li.po_number == po.po_number

    def test_po_number_is_empty_when_the_line_has_no_purchase_order_item(self, db_session):
        """A transient line whose relationship/FK was never set. `purchase_order_item`
        is `nullable=False` in the DB, but this object is never committed -- the
        property must degrade to '' here too, not only on a persisted row."""
        from app.receiving_reports.models import ReceivingReportItem
        li = ReceivingReportItem(line_number=1, received_quantity=Decimal('5'))
        assert li.purchase_order_item is None
        assert li.po_number == ''

    def test_po_number_is_empty_when_the_po_line_itself_has_no_order(self, db_session):
        """The other missing link: the PO line exists but is not attached to any
        PurchaseOrder header (`.order`, the REAL backref, is None). Exercises the
        second `if` branch of the property -- the first test above cannot reach it,
        since its `poi` is always attached to a committed `po`."""
        from app.receiving_reports.models import ReceivingReportItem
        from app.purchase_orders.models import PurchaseOrderItem
        poi = PurchaseOrderItem(line_number=1, quantity=Decimal('10'))
        assert poi.order is None
        li = ReceivingReportItem(line_number=1, received_quantity=Decimal('5'))
        li.purchase_order_item = poi
        assert li.po_number == ''

    def test_po_number_never_reads_a_purchase_order_attribute(self, db_session):
        """Pins the exact defect the plan's own Step 2 snippet would have shipped:
        `purchase_order_item.purchase_order` is not a real relationship
        (PurchaseOrderItem's backref is `order`), so a property written that way
        raises AttributeError instead of degrading to ''. A real PO line, with a
        real order, is used so the wrong attribute would actually be reached."""
        from app.receiving_reports.models import ReceivingReportItem
        po = _po_with_line(db_session, qty=100)
        poi = po.line_items[0]
        assert not hasattr(poi, 'purchase_order')
        li = ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                 received_quantity=Decimal('5'))
        li.purchase_order_item = poi
        assert li.po_number == po.po_number  # does not raise
