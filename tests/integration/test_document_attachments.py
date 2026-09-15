"""Shared document attachments (PR / PO / RR / CDV) through the real HTTP routes.

Owner's rule (2026-09-15): staff can upload as long as the document has not been
approved; further uploads go through the amendment (PR/PO only). Every test
here drives /attachments/... the way the browser does, and checks the audit
log, because the CRUD-test rule says the route is the contract, not the
service.
"""
import io
import os
from datetime import date
from decimal import Decimal

import pytest
from flask import current_app

from app.accounts.models import Account
from app.attachments.models import DocumentAttachment
from app.audit.models import AuditLog
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.attachments]

PASSWORDS = {'admin': 'admin123', 'staff': 'staff123', 'accountant': 'accountant123'}


@pytest.fixture(autouse=True)
def _modules_on(db_session):
    """PR / PO / RR are optional modules, off by default in the test app; their
    pages 404 until switched on. Same shape as the other purchasing tests."""
    from app import db
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('products', 'purchase_requests', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, username, branch):
    client.post('/login', data={'username': username, 'password': PASSWORDS[username]},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id


def _staff_ready(staff_user, db_session, branch):
    """The staff fixture has no branch and no purchasing books; grant both."""
    perms = staff_user.get_book_permissions()
    perms.update({'purchase_requests': True, 'purchase_orders': True,
                  'receiving_reports': True, 'payments': True})
    staff_user.set_book_permissions(perms)
    staff_user.set_branches([branch])
    db_session.commit()


def _vendor(db_session, code='ATTV1'):
    v = Vendor.query.filter_by(code=code).first()
    if not v:
        v = Vendor(code=code, name='Attachment Vendor', check_payee_name='Attachment Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v); db_session.commit()
    return v


def _cash_account(db_session):
    a = Account.query.filter_by(code='10101').first()
    if not a:
        a = Account(code='10101', name='Cash in Bank', account_type='Asset',
                    normal_balance='debit', is_active=True)
        db_session.add(a); db_session.commit()
    return a


def make_doc(db_session, branch, doc_type, status='draft', number=None):
    """A minimal document of *doc_type* in *status*, in *branch*."""
    if doc_type == 'purchase_requests':
        from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
        d = PurchaseRequest(branch_id=branch.id, pr_number=number or 'PR-ATT-0001',
                            request_date=date(2026, 9, 15), status=status, reason='Test')
        d.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                                quantity=Decimal('1'), uom_text='bag'))
    elif doc_type == 'purchase_orders':
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
        v = _vendor(db_session)
        d = PurchaseOrder(branch_id=branch.id, po_number=number or 'PO-ATT-0001',
                          order_date=date(2026, 9, 15), vendor_id=v.id, vendor_name=v.name,
                          status=status, vat_treatment='inclusive')
        d.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                              quantity=Decimal('1'), unit_price=Decimal('100'),
                                              amount=Decimal('100')))
        d.calculate_totals()
    elif doc_type == 'receiving_reports':
        from app.receiving_reports.models import ReceivingReport
        v = _vendor(db_session)
        d = ReceivingReport(branch_id=branch.id, rr_number=number or 'RR-ATT-0001',
                            receipt_date=date(2026, 9, 15), vendor_id=v.id,
                            vendor_name=v.name, status=status)
    elif doc_type == 'cash_disbursements':
        from app.cash_disbursements.models import CashDisbursementVoucher
        v = _vendor(db_session)
        d = CashDisbursementVoucher(branch_id=branch.id, cdv_number=number or 'CDV-ATT-0001',
                                    cdv_date=date(2026, 9, 15), vendor_id=v.id,
                                    vendor_name=v.name, cash_account_id=_cash_account(db_session).id,
                                    status=status, total_amount=Decimal('0'))
    else:  # pragma: no cover
        raise ValueError(doc_type)
    db_session.add(d); db_session.commit()
    return d


DOC_TYPES = ['purchase_requests', 'purchase_orders', 'receiving_reports', 'cash_disbursements']
APPROVED = {'purchase_requests': 'approved', 'purchase_orders': 'approved',
            'receiving_reports': 'approved', 'cash_disbursements': 'posted'}


def _upload(client, doc_type, doc_id, filename='scan.pdf', content=b'%PDF-1.4 test',
            field='attachment'):
    return client.post(f'/attachments/{doc_type}/{doc_id}/upload',
                       data={field: (io.BytesIO(content), filename)},
                       content_type='multipart/form-data', follow_redirects=False)


def _rows(doc_type, doc_id):
    return DocumentAttachment.query.filter_by(document_type=doc_type, document_id=doc_id).all()


# ── Upload ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_staff_upload_on_draft_creates_row_file_and_audit(client, db_session, staff_user,
                                                          main_branch, doc_type):
    _staff_ready(staff_user, db_session, main_branch)
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'staff', main_branch)

    resp = _upload(client, doc_type, doc.id)
    assert resp.status_code == 302

    rows = _rows(doc_type, doc.id)
    assert len(rows) == 1
    att = rows[0]
    assert att.original_filename == 'scan.pdf'
    assert att.mime_type == 'application/pdf'
    assert att.uploaded_by_id == staff_user.id
    on_disk = os.path.join(current_app.config['UPLOAD_FOLDER'], doc_type, str(doc.id),
                           att.stored_filename)
    assert os.path.isfile(on_disk)

    audit = AuditLog.query.filter_by(module=f'{doc_type}_attachment', action='create').all()
    assert len(audit) == 1
    assert audit[0].record_id == att.id


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_staff_upload_refused_once_approved(client, db_session, staff_user, main_branch, doc_type):
    _staff_ready(staff_user, db_session, main_branch)
    doc = make_doc(db_session, main_branch, doc_type, status=APPROVED[doc_type])
    _login(client, 'staff', main_branch)

    resp = _upload(client, doc_type, doc.id)
    assert resp.status_code == 302
    assert _rows(doc_type, doc.id) == []
    assert AuditLog.query.filter_by(module=f'{doc_type}_attachment').count() == 0


@pytest.mark.parametrize('doc_type', ['purchase_requests', 'purchase_orders'])
def test_accountant_uploads_through_amend_path_after_approval(client, db_session,
                                                              accountant_user, main_branch,
                                                              doc_type):
    doc = make_doc(db_session, main_branch, doc_type, status='approved')
    _login(client, 'accountant', main_branch)

    resp = _upload(client, doc_type, doc.id, filename='signed.png', content=b'\x89PNG\r\n')
    assert resp.status_code == 302
    rows = _rows(doc_type, doc.id)
    assert len(rows) == 1 and rows[0].mime_type == 'image/png'


@pytest.mark.parametrize('doc_type', ['receiving_reports', 'cash_disbursements'])
def test_no_amend_path_means_frozen_even_for_admin(client, db_session, admin_user,
                                                   main_branch, doc_type):
    doc = make_doc(db_session, main_branch, doc_type, status=APPROVED[doc_type])
    _login(client, 'admin', main_branch)
    _upload(client, doc_type, doc.id)
    assert _rows(doc_type, doc.id) == []


def test_multiple_files_in_one_request_all_saved(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    resp = client.post(f'/attachments/purchase_orders/{doc.id}/upload',
                       data={'attachments': [(io.BytesIO(b'a'), 'quote1.pdf'),
                                             (io.BytesIO(b'b'), 'quote2.pdf'),
                                             (io.BytesIO(b'c'), 'photo.jpg')]},
                       content_type='multipart/form-data')
    assert resp.status_code == 302
    assert sorted(a.original_filename for a in _rows('purchase_orders', doc.id)) == \
        ['photo.jpg', 'quote1.pdf', 'quote2.pdf']


def test_disallowed_extension_is_refused_and_nothing_written(client, db_session, admin_user,
                                                             main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_requests')
    _login(client, 'admin', main_branch)
    resp = _upload(client, 'purchase_requests', doc.id, filename='evil.svg',
                   content=b'<svg onload="alert(1)"/>')
    assert resp.status_code == 302
    assert _rows('purchase_requests', doc.id) == []
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'purchase_requests', str(doc.id))
    assert not os.path.isdir(folder) or not [f for f in os.listdir(folder) if f.endswith('.svg')]


def test_upload_to_unknown_document_type_is_404(client, db_session, admin_user, main_branch):
    _login(client, 'admin', main_branch)
    resp = _upload(client, 'accounts_payable', 1)
    assert resp.status_code == 404


def test_upload_to_missing_document_is_404(client, db_session, admin_user, main_branch):
    _login(client, 'admin', main_branch)
    resp = _upload(client, 'purchase_orders', 999999)
    assert resp.status_code == 404


def test_upload_requires_login(client, db_session, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    resp = _upload(client, 'purchase_orders', doc.id)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    assert _rows('purchase_orders', doc.id) == []


def test_upload_redirects_to_safe_next_only(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    resp = client.post(f'/attachments/purchase_orders/{doc.id}/upload?next=/purchase-orders/{doc.id}/edit',
                       data={'attachment': (io.BytesIO(b'x'), 'a.pdf')},
                       content_type='multipart/form-data')
    assert resp.headers['Location'].endswith(f'/purchase-orders/{doc.id}/edit')
    resp = client.post(f'/attachments/purchase_orders/{doc.id}/upload?next=//evil.example/x',
                       data={'attachment': (io.BytesIO(b'x'), 'b.pdf')},
                       content_type='multipart/form-data')
    assert resp.headers['Location'].endswith(f'/purchase-orders/{doc.id}')


# ── Download / preview ────────────────────────────────────────────────────

def test_download_and_preview(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'receiving_reports')
    _login(client, 'admin', main_branch)
    _upload(client, 'receiving_reports', doc.id, filename='dr.pdf', content=b'%PDF-1.4 dr')
    _upload(client, 'receiving_reports', doc.id, filename='photo.png', content=b'\x89PNG\r\n')
    pdf, png = sorted(_rows('receiving_reports', doc.id), key=lambda a: a.original_filename)

    resp = client.get(f'/attachments/{pdf.id}/download')
    assert resp.status_code == 200
    assert resp.data == b'%PDF-1.4 dr'
    assert resp.headers['Content-Disposition'].startswith('attachment')
    assert 'dr.pdf' in resp.headers['Content-Disposition']
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'

    # Preview serves images inline, fully sandboxed.
    resp = client.get(f'/attachments/{png.id}/preview')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/png'
    assert 'sandbox' in resp.headers['Content-Security-Policy']

    # PDFs also preview inline (for the iframe), but under a same-origin policy
    # the browser's PDF viewer can run, not a blanket sandbox.
    resp = client.get(f'/attachments/{pdf.id}/preview')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert 'inline' in resp.headers['Content-Disposition']
    csp = resp.headers['Content-Security-Policy']
    assert 'sandbox' not in csp          # a bare sandbox blocks the PDF viewer
    assert "default-src 'none'" not in csp
    assert 'frame-ancestors' in csp      # but framing is still restricted to self
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'


def test_office_documents_are_not_previewable(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    _upload(client, 'purchase_orders', doc.id, filename='sheet.xlsx',
            content=b'PK\x03\x04 fake xlsx')
    att = _rows('purchase_orders', doc.id)[0]
    assert att.mime_type.endswith('spreadsheetml.sheet')
    assert client.get(f'/attachments/{att.id}/preview').status_code == 404


def test_download_missing_row_is_404(client, db_session, admin_user, main_branch):
    _login(client, 'admin', main_branch)
    assert client.get('/attachments/424242/download').status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────

def _staff_upload_one(client, db_session, staff_user, main_branch, doc_type, status='draft'):
    _staff_ready(staff_user, db_session, main_branch)
    doc = make_doc(db_session, main_branch, doc_type, status=status)
    _login(client, 'staff', main_branch)
    _upload(client, doc_type, doc.id)
    att = _rows(doc_type, doc.id)[0]
    return doc, att


def test_uploader_can_delete_own_file_on_draft(client, db_session, staff_user, main_branch):
    doc, att = _staff_upload_one(client, db_session, staff_user, main_branch, 'purchase_orders')
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'purchase_orders', str(doc.id),
                        att.stored_filename)
    assert os.path.isfile(path)

    resp = client.post(f'/attachments/{att.id}/delete')
    assert resp.status_code == 302
    assert _rows('purchase_orders', doc.id) == []
    assert not os.path.exists(path)
    audit = AuditLog.query.filter_by(module='purchase_orders_attachment', action='delete').all()
    assert len(audit) == 1 and audit[0].record_id == att.id


def test_other_staff_cannot_delete_a_colleagues_file(client, db_session, staff_user,
                                                     main_branch):
    from app.users.models import User
    doc, att = _staff_upload_one(client, db_session, staff_user, main_branch, 'purchase_orders')
    other = User(username='staff2', email='s2@test.com', full_name='Staff Two', role='staff',
                 is_active=True)
    other.set_password('staff123')
    other.set_book_permissions({'accounts_payable': True, 'payments': True})
    db_session.add(other); db_session.flush(); other.set_branches([main_branch]); db_session.commit()
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'username': 'staff2', 'password': 'staff123'}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    client.post(f'/attachments/{att.id}/delete')
    assert len(_rows('purchase_orders', doc.id)) == 1


def test_accountant_can_delete_anyones_file(client, db_session, staff_user, accountant_user,
                                            main_branch):
    doc, att = _staff_upload_one(client, db_session, staff_user, main_branch, 'purchase_orders')
    client.get('/logout', follow_redirects=True)
    _login(client, 'accountant', main_branch)
    client.post(f'/attachments/{att.id}/delete')
    assert _rows('purchase_orders', doc.id) == []


def test_delete_closed_once_approved_for_staff(client, db_session, staff_user, main_branch):
    doc, att = _staff_upload_one(client, db_session, staff_user, main_branch, 'receiving_reports')
    doc.status = 'approved'; db_session.commit()
    client.post(f'/attachments/{att.id}/delete')
    assert len(_rows('receiving_reports', doc.id)) == 1


# ── Pages: panel placement and the create-form queue ──────────────────────

DETAIL_URL = {'purchase_requests': '/purchase-requests/{id}',
              'purchase_orders': '/purchase-orders/{id}',
              'receiving_reports': '/receiving-reports/{id}',
              'cash_disbursements': '/cash-disbursements/{id}'}


def _upload_action(doc_type, doc_id):
    return f'action="/attachments/{doc_type}/{doc_id}/upload"'


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_detail_page_of_a_draft_offers_upload_and_lists_files(client, db_session, admin_user,
                                                              main_branch, doc_type):
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'admin', main_branch)
    _upload(client, doc_type, doc.id, filename='signed-copy.pdf')

    body = client.get(DETAIL_URL[doc_type].format(id=doc.id)).data.decode()
    assert _upload_action(doc_type, doc.id) in body
    assert 'signed-copy.pdf' in body
    assert f'/attachments/{_rows(doc_type, doc.id)[0].id}/download' in body


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_detail_page_once_approved_shows_files_but_no_upload_for_staff(client, db_session,
                                                                       staff_user, main_branch,
                                                                       doc_type):
    _staff_ready(staff_user, db_session, main_branch)
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'staff', main_branch)
    _upload(client, doc_type, doc.id, filename='before-approval.pdf')
    doc.status = APPROVED[doc_type]; db_session.commit()

    body = client.get(DETAIL_URL[doc_type].format(id=doc.id)).data.decode()
    assert 'before-approval.pdf' in body                 # evidence stays visible
    assert _upload_action(doc_type, doc.id) not in body  # but no upload form
    assert 'Uploads are closed' in body


@pytest.mark.parametrize('doc_type', ['purchase_requests', 'purchase_orders'])
def test_amend_page_offers_upload_to_an_approver(client, db_session, accountant_user,
                                                 main_branch, doc_type):
    doc = make_doc(db_session, main_branch, doc_type, status='approved')
    _login(client, 'accountant', main_branch)
    url = DETAIL_URL[doc_type].format(id=doc.id) + '/amend'
    body = client.get(url).data.decode()
    assert _upload_action(doc_type, doc.id) in body
    # The panel sends the user back to the amend page after an upload.
    assert f'name="next" value="{url}"' in body


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_edit_page_of_a_draft_offers_upload(client, db_session, admin_user, main_branch,
                                            doc_type):
    doc = make_doc(db_session, main_branch, doc_type)
    _login(client, 'admin', main_branch)
    body = client.get(DETAIL_URL[doc_type].format(id=doc.id) + '/edit').data.decode()
    assert _upload_action(doc_type, doc.id) in body


@pytest.mark.parametrize('doc_type', DOC_TYPES)
def test_create_page_carries_the_queue_input_and_multipart_form(client, db_session,
                                                                admin_user, main_branch,
                                                                doc_type):
    _login(client, 'admin', main_branch)
    base = DETAIL_URL[doc_type].split('/{id}')[0]
    body = client.get(base + '/create').data.decode()
    assert 'enctype="multipart/form-data"' in body
    assert 'id="createAttachments" name="attachments" multiple' in body
    assert 'js/attachment_queue.js' in body


def test_pr_create_saves_the_queued_files_after_the_document(client, db_session, admin_user,
                                                             main_branch):
    import json
    from app.purchase_requests.models import PurchaseRequest
    _login(client, 'admin', main_branch)
    data = {
        'pr_number': 'PR-QUEUE-1', 'request_date': '2026-09-15', 'reason': 'queue test',
        'line_items': json.dumps([{'description': 'Cement', 'quantity': '5'}]),
        'attachments': [(io.BytesIO(b'%PDF-1.4 signed'), 'signed-pr.pdf'),
                        (io.BytesIO(b'\x89PNG\r\n'), 'photo.png'),
                        (io.BytesIO(b'<svg/>'), 'bad.svg')],
    }
    resp = client.post('/purchase-requests/create', data=data,
                       content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    pr = PurchaseRequest.query.filter_by(pr_number='PR-QUEUE-1').one()
    names = sorted(a.original_filename for a in _rows('purchase_requests', pr.id))
    assert names == ['photo.png', 'signed-pr.pdf']
    body = resp.data.decode()
    assert 'bad.svg' in body and 'skipped' in body      # the warning names the bad file


# ── Completeness resolver (kind-aware) ─────────────────────────────────────

def _set_kind(doc_type, doc_id, filename, kind):
    """Upload helper that tags the stored row with a kind (simulates a slot upload)."""
    from app.attachments.models import DocumentAttachment
    att = DocumentAttachment.query.filter_by(document_type=doc_type, document_id=doc_id,
                                             original_filename=filename).first()
    att.kind = kind
    from app import db
    db.session.commit()


def test_missing_required_reflects_present_kinds(client, db_session, admin_user, main_branch):
    from app.attachments.completeness import missing_required
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    # PO requires signed_po + vendor_quotation. Start: both missing.
    miss = [s.key for s in missing_required('purchase_orders', doc)]
    assert miss == ['signed_po', 'vendor_quotation']

    # Attach a file and tag it signed_po → only vendor_quotation remains.
    _upload(client, 'purchase_orders', doc.id, filename='po.pdf')
    _set_kind('purchase_orders', doc.id, 'po.pdf', 'signed_po')
    miss = [s.key for s in missing_required('purchase_orders', doc)]
    assert miss == ['vendor_quotation']

    # Attach the quotation → complete.
    _upload(client, 'purchase_orders', doc.id, filename='quote.pdf')
    _set_kind('purchase_orders', doc.id, 'quote.pdf', 'vendor_quotation')
    assert missing_required('purchase_orders', doc) == []


def test_incomplete_map_is_batched_over_many_docs(client, db_session, admin_user, main_branch):
    from app.attachments.completeness import incomplete_map
    _login(client, 'admin', main_branch)
    d1 = make_doc(db_session, main_branch, 'purchase_orders', number='PO-INC-1')
    d2 = make_doc(db_session, main_branch, 'purchase_orders', number='PO-INC-2')
    # d1 gets both required files; d2 gets none.
    for fn, kind in [('a.pdf', 'signed_po'), ('b.pdf', 'vendor_quotation')]:
        _upload(client, 'purchase_orders', d1.id, filename=fn)
        _set_kind('purchase_orders', d1.id, fn, kind)

    result = incomplete_map('purchase_orders', [d1, d2])
    assert d1.id not in result                       # complete
    assert [s.key for s in result[d2.id]] == ['signed_po', 'vendor_quotation']


def test_cv_check_copy_only_required_when_paid_by_check(client, db_session, admin_user, main_branch):
    from app.attachments.completeness import missing_required
    cash = make_doc(db_session, main_branch, 'cash_disbursements', number='CDV-CASH-1')
    cash.payment_method = 'cash'; db_session.commit()
    assert [s.key for s in missing_required('cash_disbursements', cash)] == ['signed_cv']

    chk = make_doc(db_session, main_branch, 'cash_disbursements', number='CDV-CHK-1')
    chk.payment_method = 'check'; db_session.commit()
    assert [s.key for s in missing_required('cash_disbursements', chk)] == ['signed_cv', 'check_copy']


# ── Per-slot checklist panel (task 5) ──────────────────────────────────────

def test_slot_upload_tags_kind_and_checklist_shows_status(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)

    # Upload into the signed_po slot (kind carried on the form).
    resp = client.post(f'/attachments/purchase_orders/{doc.id}/upload',
                       data={'kind': 'signed_po',
                             'attachments': (io.BytesIO(b'%PDF-1.4'), 'signed.pdf')},
                       content_type='multipart/form-data')
    assert resp.status_code == 302
    row = _rows('purchase_orders', doc.id)[0]
    assert row.original_filename == 'signed.pdf' and row.kind == 'signed_po'

    body = client.get(f'/purchase-orders/{doc.id}').data.decode()
    # signed_po now filled (check), vendor_quotation still required-missing.
    assert 'signed.pdf' in body
    assert '1 required file missing' in body       # only vendor_quotation left


def test_unknown_kind_is_stored_as_other(client, db_session, admin_user, main_branch):
    doc = make_doc(db_session, main_branch, 'purchase_orders')
    _login(client, 'admin', main_branch)
    client.post(f'/attachments/purchase_orders/{doc.id}/upload',
                data={'kind': 'not_a_real_slot',
                      'attachments': (io.BytesIO(b'%PDF-1.4'), 'x.pdf')},
                content_type='multipart/form-data')
    row = _rows('purchase_orders', doc.id)[0]
    assert row.kind is None                        # normalised to Other
