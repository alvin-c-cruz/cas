import pytest
from datetime import date
from app import db
from app.purchase_requests.models import PurchaseRequest
from app.purchase_requests.utils import compute_pr_summary

pytestmark = [pytest.mark.unit]


def _pr(branch_id, status, number):
    pr = PurchaseRequest(branch_id=branch_id, pr_number=number,
                          request_date=date(2026, 7, 11), status=status)
    db.session.add(pr)
    db.session.commit()
    return pr


def test_compute_pr_summary_counts_by_status(db_session, main_branch, branch_manila):
    _pr(main_branch.id, 'draft', 'PR-SUM-001')
    _pr(main_branch.id, 'draft', 'PR-SUM-002')
    _pr(main_branch.id, 'submitted', 'PR-SUM-003')
    _pr(main_branch.id, 'approved', 'PR-SUM-004')
    _pr(main_branch.id, 'converted', 'PR-SUM-005')
    _pr(branch_manila.id, 'draft', 'PR-SUM-006')  # other branch -- must not count

    summary = compute_pr_summary(main_branch.id)

    assert summary['draft_count'] == 2
    assert summary['pending_approval_count'] == 1
    assert summary['approved_count'] == 1
    assert summary['converted_count'] == 1
