"""Soft gate at approval/posting (task 6): a document approved with required
attachment slots empty is allowed through, but the missing set is snapshotted on
the document (in the approval transaction) and audited. The server re-checks, so
a direct POST that skips the client dialog is recorded the same way.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.attachments]


@pytest.fixture(autouse=True)
def _po_on(db_session):
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


def _submitted_po(db_session, branch, vendor, number='PO-SG-1'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 9, 15),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='submitted',
                       vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal('1'), unit_price=Decimal('100'),
                                           amount=Decimal('100')))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def test_approve_with_missing_required_is_allowed_and_snapshotted(
        client, accountant_user, main_branch, vl_vendor, db_session):
    po = _submitted_po(db_session, main_branch, vl_vendor)
    _login(client, accountant_user, main_branch)

    # No attachments at all → both PO slots required and missing.
    resp = client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(po)
    # Soft gate: approval went through.
    assert po.status == 'approved'
    # Snapshot recorded the missing required slots.
    assert set(json.loads(po.approved_incomplete_slots)) == {'signed_po', 'vendor_quotation'}
    # Audited as approved-with-missing.
    audit = AuditLog.query.filter_by(module='purchase_orders').all()
    assert any('missing' in (a.notes or '').lower() for a in audit)


def test_approve_complete_leaves_no_incomplete_marker(
        client, accountant_user, main_branch, vl_vendor, db_session):
    from app.attachments.models import DocumentAttachment
    from app.utils import ph_now
    po = _submitted_po(db_session, main_branch, vl_vendor, number='PO-SG-2')
    # Fill both required slots.
    for kind in ('signed_po', 'vendor_quotation'):
        db.session.add(DocumentAttachment(
            document_type='purchase_orders', document_id=po.id, kind=kind,
            original_filename=f'{kind}.pdf', stored_filename=f'{kind}-x.pdf',
            mime_type='application/pdf', file_size=10, uploaded_by_id=accountant_user.id,
            uploaded_at=ph_now()))
    db.session.commit()
    _login(client, accountant_user, main_branch)

    client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
    db_session.refresh(po)
    assert po.status == 'approved'
    assert po.approved_incomplete_slots is None      # complete → no marker


def test_direct_post_bypassing_dialog_is_still_recorded(
        client, accountant_user, main_branch, vl_vendor, db_session):
    """The confirm dialog is client-side; a raw POST must be recorded identically."""
    po = _submitted_po(db_session, main_branch, vl_vendor, number='PO-SG-3')
    _login(client, accountant_user, main_branch)
    # A bare POST (no dialog interaction) is what a scripted client sends.
    client.post(f'/purchase-orders/{po.id}/approve')
    db_session.refresh(po)
    assert po.status == 'approved'
    assert json.loads(po.approved_incomplete_slots)   # missing set recorded
