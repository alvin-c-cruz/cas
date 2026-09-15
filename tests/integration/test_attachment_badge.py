"""Post-approval "Incomplete" badge (task 8): computed from the approval-time
snapshot intersected with currently-missing files; self-heals when completed;
frozen against later config changes."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.attachments.completeness import approved_incomplete
from app.attachments.models import DocumentAttachment
from app.utils import ph_now

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


def _approved_po(db_session, branch, vendor, snapshot, number='PO-BADGE-1'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number, order_date=date(2026, 9, 15),
                       vendor_id=vendor.id, vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive',
                       approved_incomplete_slots=json.dumps(snapshot))
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal('1'), unit_price=Decimal('100'),
                                           amount=Decimal('100')))
    po.calculate_totals()
    db_session.add(po); db_session.commit()
    return po


def _attach(db_session, po, kind, user):
    db.session.add(DocumentAttachment(
        document_type='purchase_orders', document_id=po.id, kind=kind,
        original_filename=f'{kind}.pdf', stored_filename=f'{kind}-{po.id}.pdf',
        mime_type='application/pdf', file_size=10, uploaded_by_id=user.id,
        uploaded_at=ph_now()))
    db.session.commit()


def test_badge_shows_snapshot_slots_still_missing(db_session, admin_user, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, ['signed_po', 'vendor_quotation'])
    assert set(approved_incomplete('purchase_orders', po)) == {'signed_po', 'vendor_quotation'}


def test_badge_self_heals_when_files_added(db_session, admin_user, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, ['signed_po', 'vendor_quotation'],
                      number='PO-BADGE-2')
    _attach(db_session, po, 'signed_po', admin_user)
    assert approved_incomplete('purchase_orders', po) == ['vendor_quotation']
    _attach(db_session, po, 'vendor_quotation', admin_user)
    assert approved_incomplete('purchase_orders', po) == []   # badge cleared


def test_no_snapshot_means_no_badge(db_session, admin_user, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, [], number='PO-BADGE-3')
    po.approved_incomplete_slots = None; db_session.commit()
    assert approved_incomplete('purchase_orders', po) == []


def test_badge_frozen_against_config_change(db_session, admin_user, main_branch, vl_vendor):
    """Un-requiring a slot in config must not clear a past approval's badge."""
    from app.settings import AppSettings
    from app.attachments import config_overrides
    po = _approved_po(db_session, main_branch, vl_vendor, ['vendor_quotation'], number='PO-BADGE-4')
    AppSettings.set_setting(config_overrides.required_key('purchase_orders', 'vendor_quotation'), '0')
    db.session.commit()
    # Snapshot is frozen: the badge still reflects what was required at approval.
    assert approved_incomplete('purchase_orders', po) == ['vendor_quotation']


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_list_and_detail_pages_render_incomplete_badge(client, db_session, admin_user, main_branch, vl_vendor):
    po = _approved_po(db_session, main_branch, vl_vendor, ['signed_po'], number='PO-BADGE-RENDER')
    _login(client, admin_user, main_branch)

    detail = client.get(f'/purchase-orders/{po.id}')
    assert detail.status_code == 200
    assert 'Incomplete' in detail.get_data(as_text=True)   # panel header badge

    listing = client.get('/purchase-orders')
    assert listing.status_code == 200
    assert 'PO-BADGE-RENDER' in listing.get_data(as_text=True)
