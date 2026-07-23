import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.purchase_orders.models import PurchaseOrder
from app.purchase_orders.utils import compute_po_summary

pytestmark = [pytest.mark.unit]


def _po(branch_id, status, number, total=Decimal('1000.00')):
    po = PurchaseOrder(branch_id=branch_id, po_number=number, order_date=date(2026, 7, 11),
                       status=status, total_amount=total, vat_treatment='inclusive')
    db.session.add(po)
    db.session.commit()
    return po


def test_compute_po_summary_counts_and_open_value(db_session, main_branch, branch_manila):
    _po(main_branch.id, 'draft', 'PO-SUM-001')
    _po(main_branch.id, 'approved', 'PO-SUM-002', total=Decimal('500.00'))
    _po(main_branch.id, 'partially_received', 'PO-SUM-003', total=Decimal('250.00'))
    _po(main_branch.id, 'closed', 'PO-SUM-004')
    _po(branch_manila.id, 'approved', 'PO-SUM-005', total=Decimal('9999.00'))  # other branch

    summary = compute_po_summary(main_branch.id)

    assert summary['draft_count'] == 1
    assert summary['open_count'] == 2  # approved + partially_received
    assert summary['closed_count'] == 1
    assert summary['open_value_total'] == Decimal('750.00')
