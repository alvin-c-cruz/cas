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


def test_list_shows_summary_tiles(client, accountant_user, main_branch, vl_vendor, db_session):
    po = _approved_po(db_session, main_branch, vl_vendor)
    _login(client, accountant_user, main_branch)
    _create_rr(client, po)
    body = client.get('/receiving-reports').data.decode('utf-8')
    assert 'Pending Billing' in body
    assert 'Billed' in body


def test_list_status_filter_narrows_results(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    po1 = _approved_po(db_session, main_branch, vl_vendor, number='PO-RRFILT-1')
    po2 = _approved_po(db_session, main_branch, vl_vendor, number='PO-RRFILT-2')
    _login(client, accountant_user, main_branch)
    _create_rr(client, po1, rr_number='RR-FILT-001')
    _create_rr(client, po2, rr_number='RR-FILT-002')
    rr = ReceivingReport.query.filter_by(rr_number='RR-FILT-001').first()
    rr.status = 'approved'
    db_session.commit()

    body = client.get('/receiving-reports?status=approved').data.decode('utf-8')
    assert 'RR-FILT-001' in body
    assert 'RR-FILT-002' not in body


def test_list_vendor_filter_narrows_results(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.vendors.models import Vendor
    other_vendor = Vendor(code='OTHER-V2', name='Other Vendor Two', tin='222-333-444-000')
    db_session.add(other_vendor); db_session.commit()
    po1 = _approved_po(db_session, main_branch, vl_vendor, number='PO-RRVEND-1')
    po2 = _approved_po(db_session, main_branch, other_vendor, number='PO-RRVEND-2')
    _login(client, accountant_user, main_branch)
    _create_rr(client, po1, rr_number='RR-VEND-001')
    _create_rr(client, po2, rr_number='RR-VEND-002')

    body = client.get(f'/receiving-reports?vendor={vl_vendor.id}').data.decode('utf-8')
    assert 'RR-VEND-001' in body
    assert 'RR-VEND-002' not in body


def test_list_search_matches_number_or_vendor_name(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.vendors.models import Vendor
    other_vendor = Vendor(code='RRSEARCH-V', name='UniqueRRSearchVendorXYZ', tin='777-888-999-000')
    db_session.add(other_vendor); db_session.commit()
    po1 = _approved_po(db_session, main_branch, vl_vendor, number='PO-RRSEARCH-1')
    po2 = _approved_po(db_session, main_branch, other_vendor, number='PO-RRSEARCH-2')
    _login(client, accountant_user, main_branch)
    _create_rr(client, po1, rr_number='RR-SEARCH-001')
    _create_rr(client, po2, rr_number='RR-SEARCH-002')

    body = client.get('/receiving-reports?q=UniqueRRSearchVendorXYZ').data.decode('utf-8')
    assert 'RR-SEARCH-002' in body
    assert 'RR-SEARCH-001' not in body


def test_list_date_range_filter_narrows_results(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    po = _approved_po(db_session, main_branch, vl_vendor)
    _login(client, accountant_user, main_branch)
    _create_rr(client, po, rr_number='RR-DATE-001')
    rr = ReceivingReport.query.filter_by(rr_number='RR-DATE-001').first()
    rr.receipt_date = date(2026, 1, 15)
    db_session.commit()
    _create_rr(client, po, received=1, rr_number='RR-DATE-002')  # _create_rr's default receipt_date is 2026-07-11

    body = client.get('/receiving-reports?date_from=2026-07-01&date_to=2026-07-31').data.decode('utf-8')
    assert 'RR-DATE-002' in body
    assert 'RR-DATE-001' not in body


def test_list_badge_reflects_status(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    po = _approved_po(db_session, main_branch, vl_vendor)
    _login(client, accountant_user, main_branch)
    _create_rr(client, po, rr_number='RR-BADGE-001')
    rr = ReceivingReport.query.filter_by(rr_number='RR-BADGE-001').first()
    rr.status = 'billed'
    db_session.commit()

    body = client.get('/receiving-reports').data.decode('utf-8')
    assert 'badge-billed' in body


def test_list_pagination_preserves_filters(client, accountant_user, main_branch, vl_vendor, db_session):
    po = _approved_po(db_session, main_branch, vl_vendor, qty=6000)
    _login(client, accountant_user, main_branch)
    for i in range(51):
        _create_rr(client, po, received=1, rr_number=f'RR-PAGE-{i:03d}')
    resp = client.get('/receiving-reports?status=draft')
    assert resp.status_code == 200
    assert b'status=draft' in resp.data


def test_list_actions_column_hides_edit_when_not_draft(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.receiving_reports.models import ReceivingReport
    po = _approved_po(db_session, main_branch, vl_vendor)
    _login(client, accountant_user, main_branch)
    _create_rr(client, po, rr_number='RR-ACT-001')
    rr = ReceivingReport.query.filter_by(rr_number='RR-ACT-001').first()
    rr.status = 'approved'
    db_session.commit()

    body = client.get('/receiving-reports').data.decode('utf-8')
    assert f'/receiving-reports/{rr.id}/edit' not in body
    assert f'/receiving-reports/{rr.id}' in body


def test_page_title_not_dashboard(client, accountant_user, main_branch, vl_vendor, db_session):
    """Regression (BUG-PURCHASES-PAGE-TITLE-DASHBOARD): list/detail/form must set their
    own page_title block, not fall through to base.html's default "Dashboard"."""
    from app.receiving_reports.models import ReceivingReport
    _login(client, accountant_user, main_branch)
    po = _approved_po(db_session, main_branch, vl_vendor)
    _create_rr(client, po)
    rr = ReceivingReport.query.first()

    list_body = client.get('/receiving-reports').data.decode('utf-8')
    assert 'Receiving Reports' in list_body

    detail_body = client.get(f'/receiving-reports/{rr.id}').data.decode('utf-8')
    assert f'Receiving Report — {rr.rr_number}' in detail_body

    create_body = client.get('/receiving-reports/create').data.decode('utf-8')
    assert 'Enter Receiving Report' in create_body
