"""Regression tests for BUG-RR-NUMBER-HARDCODED: rr_number must be user-editable on create,
mirroring PurchaseOrderForm.po_number (app/purchase_orders/forms.py)."""
import pytest
from datetime import date
from app.receiving_reports.models import ReceivingReport, generate_rr_number
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

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


_po_counter = 0


def _approved_po(db_session, branch_id, vendor_id):
    global _po_counter
    _po_counter += 1
    po = PurchaseOrder(
        branch_id=branch_id, po_number=f'PO-TEST-{_po_counter:04d}', vendor_id=vendor_id,
        vendor_name='Test Vendor', vat_treatment='inclusive', payment_terms='Net 30',
        status='approved', order_date=date(2026, 7, 17),
    )
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Test item', quantity=10, unit_price=100,
        amount=1000, vat_category='', vat_rate=0))
    db_session.add(po)
    db_session.commit()
    return po


def test_create_rr_honors_submitted_rr_number(client, accountant_user, db_session,
                                               main_branch, vl_vendor):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        po = _approved_po(db_session, main_branch.id, vl_vendor.id)
        custom_number = 'RR-CUSTOM-9001'
        resp = client.post('/receiving-reports/create', data={
            'purchase_order_id': po.id,
            'receipt_date': '2026-07-17',
            'remarks': '',
            'lines': ('[{"purchase_order_item_id": %d, "received_quantity": 10}]'
                     % po.line_items[0].id),
            'rr_number': custom_number,
        }, follow_redirects=True)
        assert resp.status_code == 200
        rr = ReceivingReport.query.filter_by(rr_number=custom_number).first()
        assert rr is not None, 'submitted rr_number was not honored (still auto-generated)'


def test_create_rr_rejects_duplicate_rr_number(client, accountant_user, db_session,
                                               main_branch, vl_vendor):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        po1 = _approved_po(db_session, main_branch.id, vl_vendor.id)
        existing = ReceivingReport(rr_number='RR-DUP-0001', branch_id=main_branch.id,
                                   receipt_date=date(2026, 7, 16), purchase_order_id=po1.id,
                                   vendor_id=vl_vendor.id, vendor_name='Test Vendor',
                                   status='draft')
        db_session.add(existing)
        db_session.commit()

        po2 = _approved_po(db_session, main_branch.id, vl_vendor.id)
        resp = client.post('/receiving-reports/create', data={
            'purchase_order_id': po2.id,
            'receipt_date': '2026-07-17',
            'remarks': '',
            'lines': ('[{"purchase_order_item_id": %d, "received_quantity": 10}]'
                     % po2.line_items[0].id),
            'rr_number': 'RR-DUP-0001',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already exists' in resp.data
        assert ReceivingReport.query.filter_by(rr_number='RR-DUP-0001').count() == 1


def test_create_rr_get_prefills_generated_number(client, accountant_user, main_branch):
    with client:
        client.post('/login', data={'username': accountant_user.username,
                                    'password': 'accountant123'}, follow_redirects=True)
        resp = client.get('/receiving-reports/create')
        assert resp.status_code == 200
        assert b'name="rr_number"' in resp.data
