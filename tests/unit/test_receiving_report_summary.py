import pytest
from datetime import date
from app import db
from app.purchase_orders.models import PurchaseOrder
from app.receiving_reports.models import ReceivingReport
from app.receiving_reports.utils import compute_rr_summary

pytestmark = [pytest.mark.unit]


def _po(number):
    # ReceivingReport.purchase_order_id is NOT NULL -- a stub PO satisfies the column
    # (SQLite FK enforcement is off app-wide, so it needn't be branch-matched).
    po = PurchaseOrder(po_number=number, status='approved', vat_treatment='inclusive')
    db.session.add(po)
    db.session.commit()
    return po


def _rr(branch_id, status, number):
    po = _po(f'PO-{number}')
    rr = ReceivingReport(branch_id=branch_id, purchase_order_id=po.id, rr_number=number,
                        receipt_date=date(2026, 7, 11), vendor_name='Test Vendor', status=status)
    db.session.add(rr)
    db.session.commit()
    return rr


def test_compute_rr_summary_counts_by_status(db_session, main_branch, branch_manila):
    _rr(main_branch.id, 'draft', 'RR-SUM-001')
    _rr(main_branch.id, 'approved', 'RR-SUM-002')
    _rr(main_branch.id, 'approved', 'RR-SUM-003')
    _rr(main_branch.id, 'billed', 'RR-SUM-004')
    _rr(branch_manila.id, 'draft', 'RR-SUM-005')  # other branch

    summary = compute_rr_summary(main_branch.id)

    assert summary['draft_count'] == 1
    assert summary['pending_billing_count'] == 2
    assert summary['billed_count'] == 1
