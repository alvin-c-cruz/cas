"""The PO(s) an RR touches are derived from its lines, not from a header column.

The header FK still exists at this task; these tests must pass WITHOUT reading it,
which is what lets Task 6 drop it.
"""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _approved_po(db_session, branch, vendor, number, qty=100):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _make_draft_rr(db_session, branch, header_po, poi_and_qty, number):
    """poi_and_qty: list of (purchase_order_item, received_qty) -- one RR line per pair.
    header_po is only used to populate the (soon-to-be-unread) header FK."""
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         purchase_order_id=header_po.id, vendor_id=header_po.vendor_id,
                         vendor_name=header_po.vendor_name, status='draft')
    for i, (poi, qty) in enumerate(poi_and_qty, start=1):
        rr.line_items.append(ReceivingReportItem(line_number=i,
                                                 purchase_order_item_id=poi.id,
                                                 received_quantity=Decimal(str(qty))))
    db_session.add(rr); db_session.commit()
    return rr


@pytest.fixture
def rr_one_po(db_session, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    return _make_draft_rr(db_session, main_branch, po,
                          [(po.line_items[0], 10)], number='RR-DERIV-0001')


@pytest.fixture
def rr_two_pos(db_session, main_branch, vl_vendor):
    po_a = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    po_b = _approved_po(db_session, main_branch, vl_vendor, number='PO-B')
    return _make_draft_rr(db_session, main_branch, po_a,
                          [(po_a.line_items[0], 10), (po_b.line_items[0], 5)],
                          number='RR-DERIV-0002')


@pytest.fixture
def rr_two_lines_one_po(db_session, main_branch, vl_vendor):
    from app.purchase_orders.models import PurchaseOrderItem
    po = _approved_po(db_session, main_branch, vl_vendor, number='PO-A')
    po.line_items.append(PurchaseOrderItem(line_number=2, description='Sand',
                                           quantity=Decimal('50'), unit_price=Decimal('5'),
                                           amount=Decimal('250')))
    db_session.add(po); db_session.commit()
    return _make_draft_rr(db_session, main_branch, po,
                          [(po.line_items[0], 10), (po.line_items[1], 5)],
                          number='RR-DERIV-0003')


class TestDerivation:

    def test_one_po_reports_that_po(self, db_session, rr_one_po):
        assert [po.po_number for po in rr_one_po.purchase_orders] == ['PO-A']
        assert rr_one_po.po_number_display == 'PO-A'

    def test_two_pos_are_both_listed_and_deduped(self, db_session, rr_two_pos):
        assert [po.po_number for po in rr_two_pos.purchase_orders] == ['PO-A', 'PO-B']
        assert rr_two_pos.po_number_display == '2 POs'

    def test_two_lines_from_ONE_po_report_that_po_once(self, db_session, rr_two_lines_one_po):
        """Control: dedupe must not collapse to 'many' just because there are 2 lines."""
        assert [po.po_number for po in rr_two_lines_one_po.purchase_orders] == ['PO-A']
        assert rr_two_lines_one_po.po_number_display == 'PO-A'

    def test_derivation_does_not_read_the_header_column(self, db_session, rr_two_pos):
        """Mutation anchor: blanking the header FK must change nothing.

        The header column is still `nullable=False` at this task (Task 6 drops it), so an
        autoflushed UPDATE with NULL would violate the live NOT NULL constraint -- that is a
        DB-schema artifact, not the thing under test. `no_autoflush` blanks the FK in memory
        only, which is all `.purchase_orders` needs to prove it never reads the column.
        """
        with db.session.no_autoflush:
            rr_two_pos.purchase_order_id = None
            assert len(rr_two_pos.purchase_orders) == 2
