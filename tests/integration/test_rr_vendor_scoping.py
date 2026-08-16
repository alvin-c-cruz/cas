"""_eligible_purchase_orders() becomes vendor-scoped: the create form's PO picker
must offer only the chosen vendor's receivable POs, in the session branch, that
still have an open line -- and offer NOTHING before a vendor is chosen (the create
view has no vendor on first load; silently returning every vendor's POs would
defeat the vendor-first design this task exists for).

Called directly, not through the route: this pins the data-layer contract Task 4's
template/picker will consume, independent of how the picker itself is built.
"""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


def _po(db_session, branch, vendor, number, qty=10, status='approved'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='OTH-VEND-VS', name='Other Vendor VS', tin='111-222-333-001')
    db_session.add(v); db_session.commit()
    return v


class TestVendorScoping:
    """Only the chosen vendor's POs are offered."""

    def test_a_po_of_the_chosen_vendor_with_an_open_line_is_offered(
            self, db_session, main_branch, vl_vendor):
        """CONTROL for every restriction test below: prove the ordinary case
        still comes through before proving narrower cases are excluded."""
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-001')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po in eligible

    def test_a_po_of_another_vendor_is_never_offered(
            self, db_session, main_branch, vl_vendor, other_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        mine = _po(db_session, main_branch, vl_vendor, 'PO-VS-002')
        theirs = _po(db_session, main_branch, other_vendor, 'PO-VS-003')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert mine in eligible
        assert theirs not in eligible


class TestNoOpenLineExcluded:
    def test_a_po_with_no_open_line_is_excluded(self, db_session, main_branch, vl_vendor):
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-004', qty=10)
        poi = po.line_items[0]
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-VS-FULL',
                             receipt_date=date(2026, 7, 11), purchase_order_id=po.id,
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                                  received_quantity=Decimal('10')))
        db_session.add(rr); db_session.commit()

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po not in eligible

    def test_a_po_still_holding_open_quantity_is_offered(self, db_session, main_branch, vl_vendor):
        """CONTROL. A partial receipt must not exhaust the whole PO's eligibility."""
        from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
        from app.receiving_reports.views import _eligible_purchase_orders
        po = _po(db_session, main_branch, vl_vendor, 'PO-VS-005', qty=10)
        poi = po.line_items[0]
        rr = ReceivingReport(branch_id=main_branch.id, rr_number='RR-VS-PARTIAL',
                             receipt_date=date(2026, 7, 11), purchase_order_id=po.id,
                             vendor_id=vl_vendor.id, vendor_name=vl_vendor.name,
                             status='approved')
        rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=poi.id,
                                                  received_quantity=Decimal('4')))
        db_session.add(rr); db_session.commit()

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert po in eligible


class TestBranchScoping:
    def test_a_po_in_another_branch_is_excluded(
            self, db_session, main_branch, branch_manila, vl_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        elsewhere = _po(db_session, branch_manila, vl_vendor, 'PO-VS-006')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert elsewhere not in eligible

    def test_the_same_po_in_the_session_branch_is_offered(
            self, db_session, main_branch, branch_manila, vl_vendor):
        """CONTROL. Same vendor, same shape of PO -- only the branch differs --
        proving the exclusion above is the branch filter, not something else."""
        from app.receiving_reports.views import _eligible_purchase_orders
        here = _po(db_session, main_branch, vl_vendor, 'PO-VS-007')

        eligible = _eligible_purchase_orders(main_branch.id, vl_vendor.id)

        assert here in eligible


class TestNoVendorChosenYet:
    """The create view has no vendor selected on first load. Silently returning
    every vendor's receivable POs at that point would defeat the whole feature."""

    def test_no_vendor_chosen_offers_nothing(self, db_session, main_branch, vl_vendor, other_vendor):
        from app.receiving_reports.views import _eligible_purchase_orders
        _po(db_session, main_branch, vl_vendor, 'PO-VS-008')
        _po(db_session, main_branch, other_vendor, 'PO-VS-009')

        assert _eligible_purchase_orders(main_branch.id, None) == []

    def test_a_falsy_vendor_id_of_zero_also_offers_nothing(self, db_session, main_branch, vl_vendor):
        """CONTROL for the exact sentinel the '-- Select vendor --' choice submits."""
        from app.receiving_reports.views import _eligible_purchase_orders
        _po(db_session, main_branch, vl_vendor, 'PO-VS-010')

        assert _eligible_purchase_orders(main_branch.id, 0) == []
