import json
from datetime import date
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


def _approved_po(db_session, branch, vendor, qty=100, number='PO-2026-07-0300'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from decimal import Decimal
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal(str(qty)), unit_price=Decimal('10'),
                                           amount=Decimal(str(qty * 10))))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


_rr_counter = 0


def _create_rr(client, po, received=60, rr_number=None):
    global _rr_counter
    if rr_number is None:
        _rr_counter += 1
        rr_number = f'RR-TEST-{_rr_counter:04d}'
    poi = po.line_items[0]
    lines = [{'purchase_order_item_id': poi.id, 'received_quantity': str(received)}]
    return client.post('/receiving-reports/create', data={
        'purchase_order_id': str(po.id), 'receipt_date': '2026-07-11',
        'remarks': 'partial delivery', 'lines': json.dumps(lines),
        'rr_number': rr_number,
    }, follow_redirects=True)


def test_create_rr_persists_and_audits(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    from app.audit.models import AuditLog
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    resp = _create_rr(client, po, received=60)
    assert resp.status_code == 200
    rr = ReceivingReport.query.filter_by(purchase_order_id=po.id).first()
    assert rr is not None
    assert rr.status == 'draft' and rr.branch_id == main_branch.id
    assert rr.vendor_name == vl_vendor.name
    assert len(rr.line_items) == 1
    assert float(rr.line_items[0].received_quantity) == 60.0
    assert AuditLog.query.filter_by(module='receiving_reports', action='create',
                                    record_id=rr.id).count() == 1


def test_create_rr_posts_no_journal_entry(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.journal_entries.models import JournalEntry
    before = JournalEntry.query.count()
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    _create_rr(client, po)
    assert JournalEntry.query.count() == before          # RR posts nothing


def test_create_requires_a_received_line(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    # all-zero line -> rejected (nothing received)
    resp = client.post('/receiving-reports/create', data={
        'purchase_order_id': str(po.id), 'receipt_date': '2026-07-11',
        'lines': json.dumps([{'purchase_order_item_id': po.line_items[0].id,
                              'received_quantity': '0'}]),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert ReceivingReport.query.count() == 0


def test_list_and_view_show_rr(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    _create_rr(client, po)
    rr = ReceivingReport.query.first()
    assert bytes(rr.rr_number, 'utf-8') in client.get('/receiving-reports').data
    assert client.get(f'/receiving-reports/{rr.id}').status_code == 200
