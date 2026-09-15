"""Attachments-only late completion (task 9): an approver may fill a still-empty
required slot on an already-approved RR / posted CV; not a non-required slot, not
a replace, not for staff."""
import io
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.attachments]

PASS = {'admin': 'admin123', 'accountant': 'accountant123', 'staff': 'staff123'}


@pytest.fixture(autouse=True)
def _on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='LCV1', name='Late Vendor', check_payee_name='Late Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v); db_session.commit(); return v


def _approved_rr(db_session, branch, vendor, number='RR-LC-1'):
    from app.receiving_reports.models import ReceivingReport
    rr = ReceivingReport(branch_id=branch.id, rr_number=number, receipt_date=date(2026, 9, 15),
                         vendor_id=vendor.id, vendor_name=vendor.name, status='approved')
    db_session.add(rr); db_session.commit(); return rr


def _rows(doc_id):
    from app.attachments.models import DocumentAttachment
    return DocumentAttachment.query.filter_by(document_type='receiving_reports', document_id=doc_id).all()


def _upload(client, rr_id, kind, fn='late.pdf'):
    return client.post(f'/attachments/receiving_reports/{rr_id}/upload',
                       data={'kind': kind, 'attachments': (io.BytesIO(b'%PDF-1.4'), fn)},
                       content_type='multipart/form-data')


def test_approver_can_fill_empty_required_slot_after_approval(client, db_session, accountant_user, main_branch):
    rr = _approved_rr(db_session, main_branch, _vendor(db_session))
    _login(client, accountant_user, main_branch)
    resp = _upload(client, rr.id, 'signed_rr')
    assert resp.status_code == 302
    rows = _rows(rr.id)
    assert len(rows) == 1 and rows[0].kind == 'signed_rr'


def test_late_fill_refused_for_non_required_other(client, db_session, accountant_user, main_branch):
    rr = _approved_rr(db_session, main_branch, _vendor(db_session), number='RR-LC-2')
    _login(client, accountant_user, main_branch)
    # No kind → Other; late completion is required-slots only → refused.
    resp = client.post(f'/attachments/receiving_reports/{rr.id}/upload',
                       data={'attachments': (io.BytesIO(b'x'), 'x.pdf')},
                       content_type='multipart/form-data')
    assert resp.status_code == 302
    assert _rows(rr.id) == []


def test_late_fill_cannot_replace_a_filled_slot(client, db_session, accountant_user, main_branch):
    rr = _approved_rr(db_session, main_branch, _vendor(db_session), number='RR-LC-3')
    _login(client, accountant_user, main_branch)
    _upload(client, rr.id, 'signed_rr', fn='first.pdf')
    _upload(client, rr.id, 'signed_rr', fn='second.pdf')   # slot already filled
    rows = _rows(rr.id)
    assert len(rows) == 1 and rows[0].original_filename == 'first.pdf'


def test_staff_cannot_late_complete(client, db_session, staff_user, main_branch):
    rr = _approved_rr(db_session, main_branch, _vendor(db_session), number='RR-LC-4')
    staff_user.set_book_permissions({'receiving_reports': True})
    staff_user.set_branches([main_branch]); db_session.commit()
    _login(client, staff_user, main_branch)
    resp = _upload(client, rr.id, 'signed_rr')
    assert resp.status_code == 302
    assert _rows(rr.id) == []
