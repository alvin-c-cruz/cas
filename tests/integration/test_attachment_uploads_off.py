"""Attachments are off (owner, 23 Oct 2026: "we are not implementing the uploading of file attachment
documents in our app. the free server got full"). app/attachments/switch.py says what off means; this
file checks it through the real routes and pages, with the switch as every server has it. The tests
of the upload feature itself run with it on (@pytest.mark.attachment_uploads)."""
import io
import json
import os
from datetime import date
from decimal import Decimal

import pytest
from flask import current_app

from app import db
from app.attachments.models import DocumentAttachment
from app.attachments.switch import OFF_MESSAGE, OFF_NOTE
from app.audit.models import AuditLog
from tests.integration.test_document_attachments import (  # noqa: F401  (_modules_on is autouse)
    APPROVED, DETAIL_URL, DOC_TYPES, _login, _modules_on, _rows, _staff_ready, _upload,
    _upload_action, make_doc,
)

pytestmark = [pytest.mark.integration, pytest.mark.attachments]


def _files_on_disk():
    root = current_app.config['UPLOAD_FOLDER']
    return sorted(os.path.relpath(os.path.join(d, f), root)
                  for d, _, names in os.walk(root) for f in names)


def _attached_before(doc_type, doc, user, filename='signed.pdf', kind=None):
    """A file as it was attached before uploads were switched off: a row and its file."""
    from app.attachments.service import upload_dir
    stored = f'{doc_type}-{doc.id}-{filename}'
    path = os.path.join(upload_dir(doc_type, doc.id), stored)
    with open(path, 'wb') as f:
        f.write(b'%PDF-1.4 attached before')
    att = DocumentAttachment(document_type=doc_type, document_id=doc.id, original_filename=filename,
                             stored_filename=stored, mime_type='application/pdf', file_size=24,
                             uploaded_by_id=user.id, kind=kind)
    db.session.add(att)
    db.session.commit()
    return att, path


def test_uploads_are_off_unless_the_server_turns_them_on(app):
    from config import Config, TestingConfig
    assert Config.ATTACHMENT_UPLOADS is False      # .env has no ATTACHMENT_UPLOADS=true
    assert TestingConfig.ATTACHMENT_UPLOADS is False
    assert app.config['ATTACHMENT_UPLOADS'] is False


# ── Nothing new is stored ──────────────────────────────────────────────────

@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_the_upload_route_refuses_and_writes_nothing(client, db_session, admin_user, main_branch, doc_type):
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'admin', main_branch)
    before = _files_on_disk()

    resp = _upload(client, doc_type, doc.id)
    assert resp.status_code == 302
    assert _rows(doc_type, doc.id) == []
    assert _files_on_disk() == before
    assert AuditLog.query.filter_by(module=f'{doc_type}_attachment').count() == 0
    assert OFF_MESSAGE in client.get(resp.headers['Location']).get_data(as_text=True)


def test_a_vendor_takes_no_file_either(client, db_session, admin_user, main_branch):
    from app.vendors.models import Vendor
    vendor = Vendor(code='OFF-VEND', name='Off Supply')
    db.session.add(vendor)
    db.session.commit()
    _login(client, 'admin', main_branch)
    client.post(f'/attachments/vendors/{vendor.id}/upload',
                data={'kind': 'bir_2303', 'attachments': (io.BytesIO(b'%PDF-1.4'), '2303.pdf')},
                content_type='multipart/form-data')
    assert _rows('vendors', vendor.id) == []


def test_a_pr_created_with_files_is_saved_without_them(client, db_session, admin_user, main_branch):
    from app.purchase_requests.models import PurchaseRequest
    _login(client, 'admin', main_branch)
    before = _files_on_disk()
    resp = client.post('/purchase-requests/create', data={
        'pr_number': 'PR-OFF-1', 'request_date': '2026-10-23', 'reason': 'uploads off',
        'line_items': json.dumps([{'description': 'Cement', 'quantity': '5'}]),
        'attachments': [(io.BytesIO(b'%PDF-1.4 signed'), 'signed-pr.pdf')],
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    pr = PurchaseRequest.query.filter_by(pr_number='PR-OFF-1').one()
    assert _rows('purchase_requests', pr.id) == []
    assert _files_on_disk() == before
    assert 'signed-pr.pdf' in resp.get_data(as_text=True)      # named in the "skipped" warning


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_no_page_offers_a_file_input(client, db_session, admin_user, main_branch, doc_type):
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'admin', main_branch)
    base = DETAIL_URL[doc_type].split('/{id}')[0]
    for url in (base + '/create', DETAIL_URL[doc_type].format(id=doc.id),
                DETAIL_URL[doc_type].format(id=doc.id) + '/edit'):
        body = client.get(url).get_data(as_text=True)
        assert 'type="file"' not in body, url
        assert _upload_action(doc_type, doc.id) not in body, url
        assert 'class="card attachments-panel"' not in body, url     # no files, so no panel at all


# ── Files attached before stay ─────────────────────────────────────────────

def test_files_attached_before_are_listed_and_can_be_deleted(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    signed, signed_path = _attached_before('purchase_orders', doc, admin_user, 'signed-po.pdf', 'signed_po')
    other, _ = _attached_before('purchase_orders', doc, admin_user, 'quote-email.pdf')
    _login(client, 'admin', main_branch)

    body = client.get(f'/purchase-orders/{doc.id}').get_data(as_text=True)
    assert 'class="card attachments-panel"' in body
    assert OFF_NOTE in body
    assert 'signed-po.pdf' in body and 'quote-email.pdf' in body
    assert f'/attachments/{signed.id}/download' in body and f'/attachments/{other.id}/download' in body
    assert 'data-slot="signed_po"' in body
    assert 'data-slot="vendor_quotation"' not in body       # an empty slot is not listed
    assert 'type="file"' not in body
    assert '*required' not in body

    assert client.get(f'/attachments/{signed.id}/download').status_code == 200
    resp = client.post(f'/attachments/{signed.id}/delete')
    assert resp.status_code == 302
    assert db.session.get(DocumentAttachment, signed.id) is None
    assert not os.path.exists(signed_path)


def test_staff_still_cannot_delete_once_approved(client, db_session, staff_user, main_branch):
    _staff_ready(staff_user, db_session, main_branch)
    doc = make_doc(db_session, main_branch, 'purchase_orders', status=APPROVED['purchase_orders'])
    att, path = _attached_before('purchase_orders', doc, staff_user)
    _login(client, 'staff', main_branch)
    client.post(f'/attachments/{att.id}/delete')
    assert db.session.get(DocumentAttachment, att.id) is not None
    assert os.path.exists(path)


# ── Nothing waits on a file ────────────────────────────────────────────────

def test_no_slot_is_required(client, db_session, admin_user, main_branch):
    from app.attachments.completeness import incomplete_map, missing_required, required_slots
    from app.attachments.service import record_approval_completeness
    docs = [make_doc(db_session, main_branch, t, number=f'OFF-{i}') for i, t in enumerate(DOC_TYPES)]
    for t, d in zip(DOC_TYPES, docs):
        assert required_slots(t, d) == [], t
        assert missing_required(t, d) == [], t
        assert incomplete_map(t, [d]) == {}, t
        assert record_approval_completeness(t, d) == [], t
        assert d.approved_incomplete_slots is None, t


def test_past_approvals_are_not_flagged_for_missing_files(client, db_session, admin_user, main_branch):
    """Philgen had 270 approved documents flagged this way on 22 Oct 2026; none can be completed now."""
    from app.attachments.completeness import approved_incomplete
    doc = make_doc(db_session, main_branch, 'purchase_orders', status='approved')
    doc.approved_incomplete_slots = json.dumps(['signed_po', 'vendor_quotation'])
    db.session.commit()
    assert approved_incomplete('purchase_orders', doc) == []
    _login(client, 'admin', main_branch)
    assert 'title="Approved with required files missing"' not in \
        client.get('/purchase-orders').get_data(as_text=True)
    assert 'class="att-approved-incomplete"' not in client.get(f'/purchase-orders/{doc.id}').get_data(as_text=True)


def test_action_items_do_not_ask_for_files(db_session, admin_user, main_branch):
    from app.dashboard.action_items_service import gather_draft_items
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    doc.created_by_id = admin_user.id      # Action Items lists the reader's own drafts
    db.session.commit()
    items = gather_draft_items(admin_user, main_branch.id)
    assert items, 'the draft PO is listed'
    assert not [i for i in items if 'attach' in i['desc']]


def test_the_sidebar_drops_required_attachments_and_its_page_says_why(client, db_session, admin_user,
                                                                      main_branch):
    _login(client, 'admin', main_branch)
    assert 'href="/settings/attachment-slots"' not in client.get('/dashboard').get_data(as_text=True)
    body = client.get('/settings/attachment-slots').get_data(as_text=True)
    assert 'class="attachment-uploads-off"' in body


# ── Accounts payable and sales invoices keep their own attachments ─────────

def _draft_ap(db_session, branch):
    from app.accounts_payable.models import AccountsPayable
    from app.vendors.models import Vendor
    vendor = Vendor(code='OFF-AP', name='Off AP Vendor', check_payee_name='Off AP Vendor', is_active=True,
                    payment_terms='Net 30')
    db_session.add(vendor)
    db_session.commit()
    ap = AccountsPayable(
        ap_number='OFF-AP-1', vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin='',
        vendor_address='', branch_id=branch.id, ap_date=date.today(), due_date=date.today(),
        status='draft', subtotal=Decimal('100.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('100.00'), withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal('100.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('100.00'), payment_terms='Net 30')
    db_session.add(ap)
    db_session.commit()
    return ap


def test_an_apv_takes_no_file_and_its_pages_offer_none(client, db_session, admin_user, main_branch):
    from app.accounts_payable.models import AccountsPayableAttachment
    ap = _draft_ap(db_session, main_branch)
    _login(client, 'admin', main_branch)
    before = _files_on_disk()

    resp = client.post(f'/accounts-payable/{ap.id}/attachments/upload',
                       data={'attachment': (io.BytesIO(b'%PDF-1.4'), 'invoice.pdf')},
                       content_type='multipart/form-data', follow_redirects=True)
    assert OFF_MESSAGE in resp.get_data(as_text=True)
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0
    assert _files_on_disk() == before

    for url in ('/accounts-payable/create', f'/accounts-payable/{ap.id}/edit', f'/accounts-payable/{ap.id}'):
        body = client.get(url).get_data(as_text=True)
        assert 'type="file"' not in body, url
        assert 'id="createAttachments"' not in body, url


def test_a_posted_apv_is_not_flagged_and_takes_no_amendment(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import APAmendmentError, create_request
    from werkzeug.datastructures import FileStorage
    ap = _draft_ap(db_session, main_branch)
    ap.status = 'posted'
    ap.approved_incomplete_slots = json.dumps(['signed_ap'])
    db.session.commit()
    _login(client, 'admin', main_branch)
    body = client.get(f'/accounts-payable/{ap.id}').get_data(as_text=True)
    assert '⚠ Incomplete' not in body
    assert 'Request amendment to attach' not in body
    with pytest.raises(APAmendmentError, match=OFF_MESSAGE):
        create_request(ap, admin_user, 'The signed copy came in late.',
                       FileStorage(io.BytesIO(b'%PDF-1.4'), filename='signed.pdf'))


def test_a_sales_invoice_takes_no_file(client, db_session, accountant_user, main_branch):
    from app.customers.models import Customer
    from app.accounts.models import Account
    from app.sales_invoices.models import SalesInvoiceAttachment
    from tests.integration.test_sales_invoices import _make_draft_invoice
    customer = Customer(code='OFF-C', name='Off Customer', is_active=True)
    revenue = Account(code='40101', name='Sales', account_type='Revenue', normal_balance='credit',
                      is_active=True)
    db.session.add_all([customer, revenue])
    db.session.commit()
    inv = _make_draft_invoice(db_session, customer, revenue, main_branch, accountant_user)
    _login(client, 'accountant', main_branch)
    before = _files_on_disk()

    resp = client.post(f'/sales-invoices/{inv.id}/attachments/upload',
                       data={'attachment': (io.BytesIO(b'%PDF-1.4'), 'po.pdf')},
                       content_type='multipart/form-data', follow_redirects=True)
    assert OFF_MESSAGE in resp.get_data(as_text=True)
    assert SalesInvoiceAttachment.query.filter_by(invoice_id=inv.id).count() == 0
    assert _files_on_disk() == before
    assert 'type="file"' not in client.get(f'/sales-invoices/{inv.id}/edit').get_data(as_text=True)


def test_the_company_logo_still_uploads(client, db_session, admin_user, main_branch):
    """The logo is not an attachment: it stays (owner, 23 Oct 2026)."""
    _login(client, 'admin', main_branch)
    assert 'name="logo"' in client.get('/settings').get_data(as_text=True)


# ── The switch, on ─────────────────────────────────────────────────────────

@pytest.mark.attachment_uploads
def test_turned_on_the_upload_works_again(client, db_session, admin_user, main_branch):
    from app.attachments.completeness import required_slots
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    _upload(client, 'purchase_orders', doc.id)
    assert len(_rows('purchase_orders', doc.id)) == 1
    assert [s.key for s in required_slots('purchase_orders', doc)] == ['signed_po', 'vendor_quotation']
