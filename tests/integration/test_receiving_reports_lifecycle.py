import json
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _approved_po(db_session, branch, vendor, qty=100, number='PO-2026-07-0400'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _make_draft_rr(db_session, branch, po, received, number='RR-2026-07-0400'):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status='draft')
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def test_approve_moves_draft_to_approved(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor, qty=100)
    rr = _make_draft_rr(db_session, main_branch, po, received=60)
    resp = client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(rr)
    assert rr.status == 'approved' and rr.approved_by_id == accountant_user.id


def test_approve_rejects_over_open_quantity(client, accountant_user, main_branch, vl_vendor, db_session):
    """The partial-receipt guard: cannot receive more than the PO line's open qty."""
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor, qty=100)
    rr = _make_draft_rr(db_session, main_branch, po, received=150)   # 150 > 100 ordered
    client.post(f'/receiving-reports/{rr.id}/approve')
    db_session.refresh(rr)
    assert rr.status == 'draft'                                      # blocked, stays draft


def test_second_rr_capped_at_remaining_open(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor, qty=100)
    rr1 = _make_draft_rr(db_session, main_branch, po, received=60, number='RR-2026-07-0401')
    client.post(f'/receiving-reports/{rr1.id}/approve')
    db_session.refresh(rr1); assert rr1.status == 'approved'         # 60 received, 40 open
    rr2 = _make_draft_rr(db_session, main_branch, po, received=60, number='RR-2026-07-0402')
    client.post(f'/receiving-reports/{rr2.id}/approve')
    db_session.refresh(rr2); assert rr2.status == 'draft'            # 60 > remaining 40 -> blocked
    # receiving exactly the remaining 40 approves
    from app.receiving_reports.models import ReceivingReportItem
    rr2.line_items[0].received_quantity = Decimal('40'); db_session.commit()
    client.post(f'/receiving-reports/{rr2.id}/approve')
    db_session.refresh(rr2); assert rr2.status == 'approved'


def test_staff_cannot_approve(client, staff_user, main_branch, vl_vendor, db_session):
    _login(client, staff_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    rr = _make_draft_rr(db_session, main_branch, po, received=10)
    client.post(f'/receiving-reports/{rr.id}/approve')
    db_session.refresh(rr); assert rr.status == 'draft'


def test_cancel_requires_reason_and_releases_qty(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import po_line_open_qty
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor, qty=100)
    rr = _make_draft_rr(db_session, main_branch, po, received=60)
    client.post(f'/receiving-reports/{rr.id}/approve')
    db_session.refresh(rr); assert rr.status == 'approved'
    assert po_line_open_qty(po.line_items[0]) == Decimal('40')       # 60 committed
    client.post(f'/receiving-reports/{rr.id}/cancel', data={'cancel_reason': 'short'})
    db_session.refresh(rr); assert rr.status == 'approved'           # <10 chars rejected
    client.post(f'/receiving-reports/{rr.id}/cancel', data={'cancel_reason': 'wrong goods returned'})
    db_session.refresh(rr); assert rr.status == 'cancelled'
    assert po_line_open_qty(po.line_items[0]) == Decimal('100')      # qty released


def test_sidebar_shows_and_hides_rr_link(client, accountant_user, main_branch, db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    _login(client, accountant_user, main_branch)
    body = client.get('/dashboard').data
    assert b'/receiving-reports' in body and b'Receiving Reports' in body
    AppSettings.set_setting('module_enabled:receiving_reports', '0')
    db_session.commit(); clear_module_config_cache()
    assert b'/receiving-reports' not in client.get('/dashboard').data


def test_print_renders(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    rr = _make_draft_rr(db_session, main_branch, po, received=10)
    resp = client.get(f'/receiving-reports/{rr.id}/print')
    assert resp.status_code == 200
    assert b'RECEIVING REPORT' in resp.data and bytes(rr.rr_number, 'utf-8') in resp.data
