import pytest
from datetime import date
from app import db
from app.receiving_reports.models import ReceivingReport
from app.receiving_reports.utils import compute_rr_summary

pytestmark = [pytest.mark.unit, pytest.mark.receiving_reports]


def _rr(branch_id, status, number):
    # vendor_id is the NOT NULL header key; SQLite FK enforcement is off app-wide,
    # so a literal id satisfies it without a Vendor row.
    rr = ReceivingReport(branch_id=branch_id, vendor_id=1, rr_number=number,
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
