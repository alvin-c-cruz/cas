import json
import pytest

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _create(client, vendor, po_number='PO-2026-07-0001', lines=None, vat_treatment='inclusive'):
    if lines is None:
        # a services line: free-text description, NO product
        lines = [{'product_id': None, 'description': 'Site clearing subcontract',
                  'quantity': None, 'unit_price': None, 'amount': '80000',
                  'vat_category': 'V12', 'vat_rate': '12'}]
    return client.post('/purchase-orders/create', data={
        'po_number': po_number, 'order_date': '2026-07-11',
        'vendor_id': str(vendor.id), 'vat_treatment': vat_treatment,
        'payment_terms': 'Net 30', 'notes': 'test',
        'line_items': json.dumps(lines),
    }, follow_redirects=True)


def test_create_draft_po_persists_and_audits(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    from app.audit.models import AuditLog
    _login(client, accountant_user, main_branch)
    resp = _create(client, vl_vendor)
    assert resp.status_code == 200
    po = PurchaseOrder.query.filter_by(po_number='PO-2026-07-0001').first()
    assert po is not None
    assert po.status == 'draft' and po.branch_id == main_branch.id
    assert po.vendor_id == vl_vendor.id and po.vendor_name == vl_vendor.name
    assert len(po.line_items) == 1
    assert po.line_items[0].description == 'Site clearing subcontract'
    assert po.line_items[0].product_id is None          # services line, no product
    assert po.total_amount == 80000                      # inclusive
    assert AuditLog.query.filter_by(module='purchase_orders', action='create',
                                    record_id=po.id).count() == 1


def test_create_posts_no_journal_entry(client, accountant_user, main_branch, vl_vendor, db_session):
    """A PO is operational: it must NOT create any journal entry."""
    from app.journal_entries.models import JournalEntry
    before = JournalEntry.query.count()
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    assert JournalEntry.query.count() == before          # zero new JEs


def test_line_requires_product_or_description(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    # a non-empty line with neither product nor description -> rejected
    bad = [{'product_id': None, 'description': '', 'quantity': '1',
            'unit_price': '10', 'amount': '10', 'vat_category': 'V12', 'vat_rate': '12'}]
    resp = _create(client, vl_vendor, po_number='PO-2026-07-0009', lines=bad)
    assert resp.status_code == 200
    assert PurchaseOrder.query.filter_by(po_number='PO-2026-07-0009').first() is None


def test_duplicate_po_number_rejected(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    _create(client, vl_vendor)                            # same number again
    assert PurchaseOrder.query.filter_by(po_number='PO-2026-07-0001').count() == 1


def test_list_and_view_show_po(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    po = PurchaseOrder.query.first()
    assert b'PO-2026-07-0001' in client.get('/purchase-orders').data
    assert client.get(f'/purchase-orders/{po.id}').status_code == 200


def test_page_title_not_dashboard(client, accountant_user, main_branch, vl_vendor, db_session):
    """Regression (BUG-PURCHASES-PAGE-TITLE-DASHBOARD): list/detail/form must set their
    own page_title block, not fall through to base.html's default "Dashboard"."""
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    po = PurchaseOrder.query.first()

    list_body = client.get('/purchase-orders').data.decode('utf-8')
    assert 'Purchase Orders' in list_body

    detail_body = client.get(f'/purchase-orders/{po.id}').data.decode('utf-8')
    assert f'Purchase Order — {po.po_number}' in detail_body

    create_body = client.get('/purchase-orders/create').data.decode('utf-8')
    assert 'Enter Purchase Order' in create_body


def test_list_shows_summary_tiles(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    body = client.get('/purchase-orders').data.decode('utf-8')
    assert 'Open' in body
    assert 'Total Open Value' in body or 'Open Value' in body


def test_list_status_filter_narrows_results(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-FILT-001')
    po = PurchaseOrder.query.filter_by(po_number='PO-FILT-001').first()
    po.status = 'approved'
    db_session.commit()
    _create(client, vl_vendor, po_number='PO-FILT-002')  # stays draft

    body = client.get('/purchase-orders?status=approved').data.decode('utf-8')
    assert 'PO-FILT-001' in body
    assert 'PO-FILT-002' not in body


def test_list_vendor_filter_narrows_results(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.vendors.models import Vendor
    other_vendor = Vendor(code='OTHER-V', name='Other Vendor', tin='111-222-333-000')
    db_session.add(other_vendor); db_session.commit()
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-VEND-001')
    _create(client, other_vendor, po_number='PO-VEND-002')

    body = client.get(f'/purchase-orders?vendor={vl_vendor.id}').data.decode('utf-8')
    assert 'PO-VEND-001' in body
    assert 'PO-VEND-002' not in body


def test_list_badge_reflects_status(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-BADGE-001')
    po = PurchaseOrder.query.filter_by(po_number='PO-BADGE-001').first()
    po.status = 'closed'
    db_session.commit()

    body = client.get('/purchase-orders').data.decode('utf-8')
    assert 'badge-closed' in body


def test_list_pagination_preserves_filters(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    for i in range(51):
        _create(client, vl_vendor, po_number=f'PO-PAGE-{i:03d}')
    resp = client.get('/purchase-orders?status=draft')
    assert resp.status_code == 200
    assert b'status=draft' in resp.data


def test_list_actions_column_hides_edit_when_not_draft(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-ACT-001')
    po = PurchaseOrder.query.filter_by(po_number='PO-ACT-001').first()
    po.status = 'approved'
    db_session.commit()

    body = client.get('/purchase-orders').data.decode('utf-8')
    assert f'/purchase-orders/{po.id}/edit' not in body
    assert f'/purchase-orders/{po.id}' in body


def test_detail_page_shows_created_by(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor)
    from app.purchase_orders.models import PurchaseOrder
    po = PurchaseOrder.query.first()
    resp = client.get(f'/purchase-orders/{po.id}')
    assert b'Created by' in resp.data
    assert b'accountant' in resp.data


def test_export_csv_respects_status_filter(client, accountant_user, main_branch, vl_vendor, db_session):
    from app.purchase_orders.models import PurchaseOrder
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-EXP-001')
    _create(client, vl_vendor, po_number='PO-EXP-002')
    po = PurchaseOrder.query.filter_by(po_number='PO-EXP-001').first()
    po.status = 'approved'
    db_session.commit()

    resp = client.get('/purchase-orders/export/csv?status=approved')
    assert resp.status_code == 200
    assert b'PO-EXP-001' in resp.data
    assert b'PO-EXP-002' not in resp.data


def test_export_excel_returns_200(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    _create(client, vl_vendor, po_number='PO-EXP-010')
    resp = client.get('/purchase-orders/export/excel')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
