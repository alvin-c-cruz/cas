"""Phase 3: billing POs/RRs into the AP. Server-side helpers + billable endpoints."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
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


def _po(db_session, branch, vendor, status='approved', number='PO-2026-07-0500', qty=100):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Subcontract',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _rr(db_session, branch, po, status='approved', received=60, number='RR-2026-07-0500'):
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 7, 11),
                         purchase_order_id=po.id, vendor_id=po.vendor_id,
                         vendor_name=po.vendor_name, status=status)
    rr.line_items.append(ReceivingReportItem(line_number=1,
                                             purchase_order_item_id=po.line_items[0].id,
                                             received_quantity=Decimal(str(received))))
    db_session.add(rr); db_session.commit()
    return rr


def _ap(branch, vendor, ap_id=9001):
    return SimpleNamespace(id=ap_id, branch_id=branch.id, vendor_id=vendor.id)


# -- setting -------------------------------------------------------------------

def test_ap_billing_consolidate_default_off(db_session):
    from app.purchase_billing import ap_billing_consolidate
    assert ap_billing_consolidate() is False


# -- bill / unbill helpers -----------------------------------------------------

def test_bill_marks_rr_billed_and_linked(db_session, main_branch, vl_vendor):
    from app.purchase_billing import _bill_purchase_sources
    po = _po(db_session, main_branch, vl_vendor)
    rr = _rr(db_session, main_branch, po)
    ap = _ap(main_branch, vl_vendor)
    _bill_purchase_sources(ap, [], [rr.id]); db_session.commit()
    db_session.refresh(rr)
    assert rr.status == 'billed' and rr.accounts_payable_id == ap.id


def test_bill_marks_po_closed_and_linked(db_session, main_branch, vl_vendor):
    from app.purchase_billing import _bill_purchase_sources
    po = _po(db_session, main_branch, vl_vendor)
    ap = _ap(main_branch, vl_vendor)
    _bill_purchase_sources(ap, [po.id], []); db_session.commit()
    db_session.refresh(po)
    assert po.status == 'closed' and po.accounts_payable_id == ap.id


def test_unbill_reverts_sources(db_session, main_branch, vl_vendor):
    from app.settings import AppSettings
    from app.purchase_billing import _bill_purchase_sources, _unbill_purchase_sources
    AppSettings.set_setting('ap_billing_consolidate', '1')   # allow 2 sources on one bill
    db_session.commit()
    po = _po(db_session, main_branch, vl_vendor)
    rr = _rr(db_session, main_branch, po)
    ap = _ap(main_branch, vl_vendor)
    _bill_purchase_sources(ap, [po.id], [rr.id]); db_session.commit()
    _unbill_purchase_sources(ap); db_session.commit()
    db_session.refresh(po); db_session.refresh(rr)
    assert po.status == 'approved' and po.accounts_payable_id is None
    assert rr.status == 'approved' and rr.accounts_payable_id is None


def test_bill_noop_when_no_ids(db_session, main_branch, vl_vendor):
    """Zhiyuan path: no source ids -> strict no-op, no error."""
    from app.purchase_billing import _bill_purchase_sources
    ap = _ap(main_branch, vl_vendor)
    _bill_purchase_sources(ap, [], [])          # must not raise


def test_bill_rejects_wrong_vendor(db_session, main_branch, vl_vendor):
    from app.purchase_billing import _bill_purchase_sources
    po = _po(db_session, main_branch, vl_vendor)
    other_ap = SimpleNamespace(id=9002, branch_id=main_branch.id, vendor_id=vl_vendor.id + 999)
    with pytest.raises(ValueError):
        _bill_purchase_sources(other_ap, [po.id], [])


def test_bill_rejects_already_billed(db_session, main_branch, vl_vendor):
    from app.purchase_billing import _bill_purchase_sources
    po = _po(db_session, main_branch, vl_vendor)
    ap = _ap(main_branch, vl_vendor)
    _bill_purchase_sources(ap, [po.id], []); db_session.commit()
    with pytest.raises(ValueError):
        _bill_purchase_sources(_ap(main_branch, vl_vendor, ap_id=9003), [po.id], [])


def test_consolidate_off_rejects_multiple(db_session, main_branch, vl_vendor):
    from app.purchase_billing import _bill_purchase_sources
    po = _po(db_session, main_branch, vl_vendor, number='PO-A')
    rr = _rr(db_session, main_branch, _po(db_session, main_branch, vl_vendor, number='PO-B'),
             number='RR-B')
    ap = _ap(main_branch, vl_vendor)
    with pytest.raises(ValueError):                 # consolidate off + 2 sources
        _bill_purchase_sources(ap, [po.id], [rr.id])


# -- endpoints -----------------------------------------------------------------

def test_billable_rrs_endpoint(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _po(db_session, main_branch, vl_vendor)
    rr = _rr(db_session, main_branch, po)
    resp = client.get(f'/receiving-reports/billable?vendor_id={vl_vendor.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(r['rr_number'] == rr.rr_number for r in data['rrs'])


def test_billable_pos_endpoint_excludes_pos_with_rr(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    services_po = _po(db_session, main_branch, vl_vendor, number='PO-SVC')     # no RR -> billable direct
    goods_po = _po(db_session, main_branch, vl_vendor, number='PO-GOODS')
    _rr(db_session, main_branch, goods_po, number='RR-GOODS')                  # has RR -> excluded
    resp = client.get(f'/purchase-orders/billable?vendor_id={vl_vendor.id}')
    assert resp.status_code == 200
    nums = [p['po_number'] for p in resp.get_json()['pos']]
    assert 'PO-SVC' in nums and 'PO-GOODS' not in nums


def test_billable_endpoints_404_when_module_off(client, admin_user, main_branch, db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:purchase_orders', '0')
    AppSettings.set_setting('module_enabled:receiving_reports', '0')
    db_session.commit(); clear_module_config_cache()
    _login(client, admin_user, main_branch)
    assert client.get('/purchase-orders/billable?vendor_id=1').status_code == 404
    assert client.get('/receiving-reports/billable?vendor_id=1').status_code == 404
