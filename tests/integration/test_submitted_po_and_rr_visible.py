"""Submitted orders and receipts are visible on their list pages (POC A).

Owner, 14 Nov 2026: "POC A" -- the PO list's "to approve" card counts submitted orders as well as drafts (Open and
Total Open Value unchanged); the RR list's status filter gets the "Submitted" option it was missing. Work order
2026-08-27-submitted-invisible-in-po-summary-and-rr-filter.md.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder
from app.purchase_orders.utils import compute_po_summary
from app.receiving_reports.models import ReceivingReport
from tests.integration.test_receiving_reports_lifecycle import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _po(branch, status, number, total='1000.00'):
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 11, 17), status=status,
                       total_amount=Decimal(total), vat_treatment='inclusive')
    db.session.add(po)
    db.session.commit()
    return po


class TestTheCard:

    def test_submitted_orders_are_counted_to_approve(self, db_session, main_branch):
        _po(main_branch, 'draft', 'D1')
        _po(main_branch, 'submitted', 'S1', total='400.00')
        _po(main_branch, 'submitted', 'S2', total='600.00')
        _po(main_branch, 'approved', 'A1', total='250.00')
        s = compute_po_summary(main_branch.id)
        assert s['draft_count'] == 3
        assert s['open_count'] == 1, 'Open unchanged: approved only'
        assert s['open_value_total'] == Decimal('250.00'), 'Total Open Value unchanged'

    def test_the_card_says_what_it_counts(self, client, accountant_user, main_branch, db_session):
        _po(main_branch, 'submitted', 'S1')
        _login(client, accountant_user, main_branch)
        html = client.get('/purchase-orders').data.decode('utf-8')
        assert 'draft or submitted' in html


class TestTheRrFilter:

    def test_submitted_is_offered_and_filters(self, client, accountant_user, main_branch, vl_vendor, db_session):
        for number, status in (('RR-S1', 'submitted'), ('RR-D1', 'draft')):
            db.session.add(ReceivingReport(branch_id=main_branch.id, rr_number=number,
                                           receipt_date=date(2026, 11, 17), vendor_id=vl_vendor.id,
                                           vendor_name=vl_vendor.name, status=status))
        db.session.commit()
        _login(client, accountant_user, main_branch)
        page = client.get('/receiving-reports').data.decode('utf-8')
        assert '<option value="submitted"' in page
        body = client.get('/receiving-reports?status=submitted').data.decode('utf-8')
        assert 'RR-S1' in body and 'RR-D1' not in body
