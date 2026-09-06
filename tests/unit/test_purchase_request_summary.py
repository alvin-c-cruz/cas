import pytest
from datetime import date
from app import db
from app.purchase_requests.models import PurchaseRequest
from app.purchase_requests.utils import compute_pr_summary

pytestmark = [pytest.mark.unit, pytest.mark.purchase_requests]


def _pr(branch_id, status, number, approved=False):
    """*approved* stamps approved_by_id, which approve() always sets.

    It matters since 2026-09-06: pending_approval_count reads the APPROVAL FACT
    rather than status == 'submitted', so a post-approval status with a NULL
    approved_by_id would read as still awaiting a signature.
    """
    pr = PurchaseRequest(branch_id=branch_id, pr_number=number,
                          request_date=date(2026, 7, 11), status=status,
                          approved_by_id=(1 if approved else None))
    db.session.add(pr)
    db.session.commit()
    return pr


def test_compute_pr_summary_counts_by_status(db_session, main_branch, branch_manila):
    _pr(main_branch.id, 'draft', 'PR-SUM-001')
    _pr(main_branch.id, 'draft', 'PR-SUM-002')
    _pr(main_branch.id, 'submitted', 'PR-SUM-003')
    _pr(main_branch.id, 'approved', 'PR-SUM-004', approved=True)
    _pr(main_branch.id, 'converted', 'PR-SUM-005', approved=True)
    _pr(branch_manila.id, 'draft', 'PR-SUM-006')  # other branch -- must not count

    summary = compute_pr_summary(main_branch.id)

    assert summary['draft_count'] == 2
    assert summary['pending_approval_count'] == 1
    assert summary['approved_count'] == 1
    assert summary['converted_count'] == 1


def test_pending_approval_counts_an_unsigned_requisition_already_on_an_order(
        db_session, main_branch):
    """THE case the 2026-09-06 decoupling created.

    A requisition pulled onto a purchase order before its signature arrives is
    moved on by recompute_pr_status, so it reads `partially_converted` while
    still unsigned. Counting only status == 'submitted' dropped exactly those
    from the card that exists to chase them -- it would have said 0 while
    somebody was still waiting to sign.
    """
    _pr(main_branch.id, 'submitted', 'PR-PEND-1')
    _pr(main_branch.id, 'partially_converted', 'PR-PEND-2')            # unsigned
    _pr(main_branch.id, 'partially_converted', 'PR-PEND-3', approved=True)  # signed
    summary = compute_pr_summary(main_branch.id)
    assert summary['pending_approval_count'] == 2


def test_pending_approval_ignores_terminal_requisitions(db_session, main_branch):
    """CONTROL: a rejected or cancelled requisition is nobody's outstanding
    signature, and a draft has not been offered for one yet."""
    for st in ('draft', 'rejected', 'cancelled'):
        _pr(main_branch.id, st, f'PR-TERM-{st}')
    assert compute_pr_summary(main_branch.id)['pending_approval_count'] == 0
