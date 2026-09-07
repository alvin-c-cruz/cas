"""A submitted receiving report can be sent back to draft.

Owner request 2026-09-07, after PO-less receipts shipped: somebody finds the purchase
order that covered the goods AFTER the receipt was submitted. A receiving report is
editable only while `draft` and has no unsubmit, so the link could not be attached at
all -- the only exits were approve or cancel.

Scope is `submitted` only. Approved and billed are out (spec decision): approved has
posted stock and GRNI, and billed cannot even be cancelled today.
"""
from datetime import date

import pytest

from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

MEMO = 'The goods were on PO-00985 after all.'


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='RTD-V', name='Return Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='RTD-P', name='Returned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _rr(db_session, branch, vendor, product, user, status='submitted',
        number='RR-RTD-1'):
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 9, 7),
                         branch_id=branch.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, status=status,
                         created_by_id=user.id,
                         submitted_by_id=(user.id if status != 'draft' else None))
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=None, product_id=product.id,
        received_quantity=3))
    db_session.add(rr); db_session.commit()
    return rr


class TestTheSchema:

    def test_the_receipt_carries_the_memo_fields(self):
        cols = {c.key for c in ReceivingReport.__table__.columns}
        assert {'return_reason', 'returned_by_id', 'returned_at'} <= cols

    def test_the_line_carries_a_no_po_reason(self):
        cols = {c.key for c in ReceivingReportItem.__table__.columns}
        assert 'no_po_reason' in cols

    def test_every_new_column_is_nullable(self):
        """Nothing to backfill: every existing row reads NULL and behaves as before."""
        for model, names in ((ReceivingReport,
                              ('return_reason', 'returned_by_id', 'returned_at')),
                             (ReceivingReportItem, ('no_po_reason',))):
            for name in names:
                assert model.__table__.c[name].nullable is True, name

    def test_only_submitted_is_returnable(self):
        """A receiving report has no `rejected` status, unlike the requisition, so
        there is exactly one source state."""
        assert ReceivingReport.RETURNABLE_STATUSES == ('submitted',)
