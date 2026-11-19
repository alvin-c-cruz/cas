"""The approver sees, on each no-PO receipt line, which open PO lines the vendor has (RR-1 A).

Owner, 17 Nov 2026: "A (my pick)" for RR-1 (work order 2026-11-13-rr-received-without-po-link). RR 00780: Fiesta's
dryer was received as a NEW product (767) with no PO link while PO 02012 had the same dryer open as product 555; the
7 Sep warning matched only the same product, so nothing fired. Now the form offers every open PO line of the vendor
(same product first; tests/e2e/test_rr_no_po_matches.py), and the RR page shows the approver those lines next to each
no-PO line while the receipt is still draft or submitted. Nothing is blocked.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture
def fiesta(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='V016', name='FIESTA APPLIANCE CENTER, INC.', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def products(db_session):
    from app.products.models import Product
    spin = Product(code='555', name='SPIN DRYER', track_inventory=False, is_active=True)
    whirl = Product(code='767', name='WHIRPOOL 4KWED4815FW DRYER', track_inventory=False, is_active=True)
    db_session.add_all([spin, whirl]); db_session.commit()
    return spin, whirl


def _po(branch, vendor, product, user, status='approved', number='02012'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 9, 9), vendor_id=vendor.id,
                       vendor_name=vendor.name, status=status, vat_treatment='inclusive', created_by_id=user.id)
    po.line_items.append(PurchaseOrderItem(line_number=1, description='FOR LAUNDRY AREA USE', quantity=Decimal('1'),
                                           unit_price=Decimal('54900'), amount=Decimal('54900'),
                                           product_id=product.id, vat_rate=Decimal('0')))
    db.session.add(po); db.session.commit()
    return po


def _direct_rr(branch, vendor, product, status='submitted', number='00780'):
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 11, 13),
                         vendor_id=vendor.id, vendor_name=vendor.name, status=status)
    rr.line_items.append(ReceivingReportItem(line_number=1, product_id=product.id, received_quantity=Decimal('1'),
                                             no_po_reason=None))
    db.session.add(rr); db.session.commit()
    return rr


def _page(client, rr):
    return client.get(f'/receiving-reports/{rr.id}').data.decode('utf-8')


def test_a_no_po_line_names_the_vendors_open_po_lines(client, db_session, main_branch, fiesta, products,
                                                      admin_user):
    spin, whirl = products
    _po(main_branch, fiesta, spin, admin_user)
    rr = _direct_rr(main_branch, fiesta, whirl)
    _login(client, admin_user, main_branch)
    html = _page(client, rr)
    assert 'data-rr-open-po-lines' in html
    assert 'PO 02012' in html and 'SPIN DRYER' in html and '1 open' in html


@pytest.mark.parametrize('status', ['approved', 'cancelled'])
def test_no_note_once_the_receipt_is_past_review(client, db_session, main_branch, fiesta, products, admin_user,
                                                 status):
    spin, whirl = products
    _po(main_branch, fiesta, spin, admin_user)
    rr = _direct_rr(main_branch, fiesta, whirl, status=status)
    _login(client, admin_user, main_branch)
    assert 'data-rr-open-po-lines' not in _page(client, rr)


def test_no_note_when_the_vendor_has_nothing_open(client, db_session, main_branch, fiesta, products, admin_user):
    spin, whirl = products
    _po(main_branch, fiesta, spin, admin_user, status='draft')       # a draft PO is not receivable
    rr = _direct_rr(main_branch, fiesta, whirl)
    _login(client, admin_user, main_branch)
    assert 'data-rr-open-po-lines' not in _page(client, rr)


def test_the_form_loads_the_matching_script(client, db_session, main_branch, admin_user):
    _login(client, admin_user, main_branch)
    html = client.get('/receiving-reports/create').data.decode('utf-8')
    assert 'js/rr_no_po_matches.js' in html
