"""Pre-approval "missing required files" surfaces in Action Items and the badge
count, and drops off once the document is approved (task 7)."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.dashboard.action_items_service import (gather_missing_attachment_items,
                                                count_action_items)

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


def _po(db_session, branch, vendor, status='draft', number='PO-AI-1', creator=None):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 9, 15),
                       vendor_id=vendor.id, vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive',
                       created_by_id=(creator.id if creator else None))
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal('1'), unit_price=Decimal('100'),
                                           amount=Decimal('100')))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def test_draft_missing_required_appears_in_action_items(db_session, admin_user, main_branch, vl_vendor):
    po = _po(db_session, main_branch, vl_vendor)
    items = gather_missing_attachment_items(admin_user, main_branch.id)
    ids = [i['id'] for i in items]
    assert po.po_number in ids
    item = next(i for i in items if i['id'] == po.po_number)
    assert 'Signed PO' in item['desc'] and 'Vendor Quotation' in item['desc']
    # And it counts toward the badge.
    assert count_action_items(admin_user, main_branch.id) >= 1


def test_approved_document_drops_off(db_session, admin_user, main_branch, vl_vendor):
    _po(db_session, main_branch, vl_vendor, status='approved', number='PO-AI-APPROVED')
    items = gather_missing_attachment_items(admin_user, main_branch.id)
    assert 'PO-AI-APPROVED' not in [i['id'] for i in items]


def test_complete_draft_not_listed(db_session, admin_user, main_branch, vl_vendor):
    from app.attachments.models import DocumentAttachment
    from app.utils import ph_now
    po = _po(db_session, main_branch, vl_vendor, number='PO-AI-COMPLETE')
    for kind in ('signed_po', 'vendor_quotation'):
        db.session.add(DocumentAttachment(
            document_type='purchase_orders', document_id=po.id, kind=kind,
            original_filename=f'{kind}.pdf', stored_filename=f'{kind}-ai.pdf',
            mime_type='application/pdf', file_size=10, uploaded_by_id=admin_user.id,
            uploaded_at=ph_now()))
    db.session.commit()
    items = gather_missing_attachment_items(admin_user, main_branch.id)
    assert 'PO-AI-COMPLETE' not in [i['id'] for i in items]
