"""The PO list shows each order's paper trail -- RR #, AP #, CD # -- the way the PR list does (RCPT A, owner 17 Nov 2026;
his RR-3 idea "maybe something similar to the PR list page"; work order 2026-11-13-rr-received-without-po-link).

Philgen's purchaser has Purchase Orders access but not Receiving Reports, AP or CDVs: he can now see from his own list
which receipts, bills and cheques each order has. A number links only where the viewer has that module.
- RR #: committed receiving reports (approved or billed) against the order's lines.
- AP #: the AP voucher that billed the order itself, and those that billed its receipts.
- CD #: the CDVs that paid those AP vouchers, and those that settled its receipts outside AP.
"""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher, CDVApLine
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_receiving_reports_lifecycle import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _po(branch, vendor, number, status='approved', ap=None):
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 11, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, status=status, vat_treatment='inclusive',
                       accounts_payable_id=ap.id if ap else None)
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Item', quantity=Decimal('5'),
                                           unit_price=Decimal('10'), amount=Decimal('50')))
    db.session.add(po); db.session.commit()
    return po


def _rr(branch, vendor, po, number, status='approved', ap=None, cdv=None):
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 11, 3), vendor_id=vendor.id,
                         vendor_name=vendor.name, status=status, accounts_payable_id=ap.id if ap else None,
                         settled_cdv_id=cdv.id if cdv else None)
    rr.line_items.append(ReceivingReportItem(line_number=1, purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal('5')))
    db.session.add(rr); db.session.commit()
    return rr


def _ap(branch, vendor, number):
    ap = AccountsPayable(ap_number=number, ap_date=date(2026, 11, 5), due_date=date(2026, 12, 5), vendor_id=vendor.id,
                         vendor_name=vendor.name, branch_id=branch.id, status='posted')
    db.session.add(ap); db.session.commit()
    return ap


def _cdv(branch, vendor, cash_account, number, pays=None):
    cdv = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number, cdv_date=date(2026, 11, 6),
                                  payee_type='vendor', payee_id=vendor.id, vendor_id=vendor.id,
                                  vendor_name=vendor.name, cash_account_id=cash_account.id, status='posted')
    db.session.add(cdv); db.session.commit()
    if pays:
        db.session.add(CDVApLine(cdv_id=cdv.id, line_number=1, ap_id=pays.id, ap_number=pays.ap_number,
                                 original_balance=Decimal('50'), amount_applied=Decimal('50')))
        db.session.commit()
    return cdv


def _row(html, po_number):
    m = re.search(r'<tr>\s*<td><a [^>]*>%s</a></td>(.*?)</tr>' % re.escape(po_number), html, re.S)
    assert m, f'no list row for {po_number}'
    return m.group(1)


@pytest.fixture
def trail(db_session, main_branch, vl_vendor, cash_account):
    """PO-A: received (RR-A1, billed by APV AP-1, paid by CD-1) + a draft RR that must not show.
       PO-B: billed by APV AP-2 itself, paid by CD-2.
       PO-C: received (RR-C1) and settled outside AP by CD-3."""
    b, v = main_branch, vl_vendor
    ap1, ap2 = _ap(b, v, 'AP-1'), _ap(b, v, 'AP-2')
    cd1 = _cdv(b, v, cash_account, 'CD-1', pays=ap1)
    _cdv(b, v, cash_account, 'CD-2', pays=ap2)
    cd3 = _cdv(b, v, cash_account, 'CD-3')
    po_a = _po(b, v, 'PO-A')
    _rr(b, v, po_a, 'RR-A1', status='billed', ap=ap1)
    _rr(b, v, po_a, 'RR-A2', status='draft')
    _po(b, v, 'PO-B', status='closed', ap=ap2)
    po_c = _po(b, v, 'PO-C')
    _rr(b, v, po_c, 'RR-C1', status='billed', cdv=cd3)
    return cd1


class TestTheColumns:

    def test_headers_like_the_pr_list(self, client, admin_user, main_branch, trail):
        _login(client, admin_user, main_branch)
        html = client.get('/purchase-orders').get_data(as_text=True)
        assert re.search(r'<th>RR #</th>\s*<th>AP #</th>\s*<th>CD #</th>', html)

    def test_received_billed_and_paid(self, client, admin_user, main_branch, trail):
        _login(client, admin_user, main_branch)
        row = _row(client.get('/purchase-orders').get_data(as_text=True), 'PO-A')
        assert 'RR-A1' in row and 'AP-1' in row and 'CD-1' in row
        assert 'RR-A2' not in row, 'a draft receipt has received nothing'

    def test_billed_by_apv_itself(self, client, admin_user, main_branch, trail):
        _login(client, admin_user, main_branch)
        row = _row(client.get('/purchase-orders').get_data(as_text=True), 'PO-B')
        assert 'AP-2' in row and 'CD-2' in row

    def test_settled_outside_ap(self, client, admin_user, main_branch, trail):
        _login(client, admin_user, main_branch)
        row = _row(client.get('/purchase-orders').get_data(as_text=True), 'PO-C')
        assert 'RR-C1' in row and 'CD-3' in row


class TestLinksFollowAccess:

    def test_numbers_link_for_a_viewer_with_the_modules(self, client, admin_user, main_branch, trail):
        _login(client, admin_user, main_branch)
        row = _row(client.get('/purchase-orders').get_data(as_text=True), 'PO-A')
        assert re.search(r'<a href="/receiving-reports/\d+">RR-A1</a>', row)
        assert re.search(r'<a href="/accounts-payable/\d+">AP-1</a>', row)
        assert re.search(r'<a href="/cash-disbursements/\d+">CD-1</a>', row)

    def test_plain_numbers_for_a_purchaser_with_po_access_only(self, client, db_session, staff_user, main_branch,
                                                               trail):
        perms = {'purchase_orders': True, 'purchase_requests': True}
        staff_user.set_book_permissions(perms)
        staff_user.set_branches([main_branch])
        db_session.commit()
        from flask import g
        g.pop('_login_user', None)
        _login(client, staff_user, main_branch)
        resp = client.get('/purchase-orders')
        assert resp.status_code == 200
        row = _row(resp.get_data(as_text=True), 'PO-A')
        assert 'RR-A1' in row and 'AP-1' in row and 'CD-1' in row, 'he sees the numbers'
        assert 'href="/receiving-reports/' not in row and 'href="/accounts-payable/' not in row \
            and 'href="/cash-disbursements/' not in row, 'but no links he could not open'
