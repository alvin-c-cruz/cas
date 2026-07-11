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


def _make_draft_po(db_session, branch, vendor, number='PO-2026-07-0100'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from datetime import date
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 7, 11),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='draft',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=1, unit_price=100, amount=100))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def test_approve_moves_draft_to_approved(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    resp = client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(po)
    assert po.status == 'approved' and po.approved_by_id == accountant_user.id


def test_staff_cannot_approve(client, staff_user, main_branch, vl_vendor, db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    # staff needs the module granted per-user; staff_user fixture grants all books
    _login(client, staff_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    client.post(f'/purchase-orders/{po.id}/approve')
    db_session.refresh(po)
    assert po.status == 'draft'          # staff is below the approver gate


def test_cancel_requires_reason(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    client.post(f'/purchase-orders/{po.id}/cancel', data={'cancel_reason': 'too short'})
    db_session.refresh(po)
    assert po.status == 'draft'          # <10 chars rejected
    client.post(f'/purchase-orders/{po.id}/cancel',
                data={'cancel_reason': 'vendor discontinued the item'})
    db_session.refresh(po)
    assert po.status == 'cancelled' and po.cancel_reason == 'vendor discontinued the item'


def test_edit_blocked_after_approve(client, accountant_user, main_branch, vl_vendor, db_session):
    _login(client, accountant_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    client.post(f'/purchase-orders/{po.id}/approve')
    resp = client.get(f'/purchase-orders/{po.id}/edit', follow_redirects=False)
    assert resp.status_code in (302, 303)     # redirected away (only drafts editable)


def test_edit_draft_updates_and_audits(client, accountant_user, main_branch, vl_vendor, db_session):
    import json
    from app.audit.models import AuditLog
    _login(client, accountant_user, main_branch)
    po = _make_draft_po(db_session, main_branch, vl_vendor)
    lines = [{'product_id': None, 'description': 'Revised cement order',
              'quantity': '2', 'unit_price': '150', 'amount': '300',
              'vat_category': 'V12', 'vat_rate': '12'}]
    resp = client.post(f'/purchase-orders/{po.id}/edit', data={
        'po_number': po.po_number, 'order_date': '2026-07-11',
        'vendor_id': str(vl_vendor.id), 'vat_treatment': 'inclusive',
        'payment_terms': 'Net 30', 'notes': 'revised',
        'row_version': po.row_version,
        'line_items': json.dumps(lines),
    }, follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(po)
    assert po.total_amount == 300
    assert po.line_items[0].description == 'Revised cement order'
    assert AuditLog.query.filter_by(module='purchase_orders', action='update',
                                    record_id=po.id).count() >= 1
