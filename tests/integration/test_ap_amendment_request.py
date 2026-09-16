import io
from datetime import date
from decimal import Decimal
import pytest
from app import db
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]

def _posted_incomplete_ap(db_session, main_branch):
    from app.accounts_payable.models import AccountsPayable
    from app.customers.models import Customer  # noqa: not needed; AP uses vendor
    from app.vendors.models import Vendor
    from app.attachments.service import record_approval_completeness
    v = Vendor(code='APV9', name='Amend Vendor', check_payee_name='Amend Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v); db_session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-AMEND-1',
                         ap_date=date(2026, 9, 16), due_date=date(2026, 10, 16),
                         vendor_id=v.id, vendor_name=v.name, status='posted',
                         total_amount=Decimal('100'), notes='')
    db_session.add(ap); db_session.commit()
    # Mirror the real posting workflow: snapshot the required slots that were
    # empty at approval/post time onto approved_incomplete_slots, which is what
    # attachment_incomplete_count() (the detail-page badge/UI gate) reads.
    record_approval_completeness('accounts_payable', ap)
    db_session.commit()
    return ap

def _fs(name='signed.pdf', data=b'%PDF-1.4'):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type='application/pdf')

def test_create_stages_file_and_stays_pending(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, _staged_dir
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs())
    db.session.commit()
    assert req.is_pending and req.kind == 'signed_ap'
    assert os.path.isfile(os.path.join(_staged_dir(req.id), req.staged_stored_filename))
    # Nothing committed onto the AP yet.
    from app.accounts_payable.models import AccountsPayableAttachment
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0

def test_approve_commits_file_into_ap_and_clears_slot(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, approve_request
    from app.accounts_payable.models import AccountsPayableAttachment
    from app.attachments.completeness import missing_required
    ap = _posted_incomplete_ap(db_session, main_branch)
    assert 'signed_ap' in [s.key for s in missing_required('accounts_payable', ap)]
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    att = approve_request(req, admin_user); db.session.commit()
    assert att.kind == 'signed_ap' and att.ap_id == ap.id
    assert req.status == 'approved' and req.reviewed_by_id == admin_user.id
    assert missing_required('accounts_payable', ap) == []   # slot now filled

def test_reject_discards_staged_file(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, reject_request, _staged_dir
    from app.accounts_payable.models import AccountsPayableAttachment
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'wrong file attached', _fs()); db.session.commit()
    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    reject_request(req, admin_user, 'not the signed AP'); db.session.commit()
    assert req.status == 'rejected'
    assert not os.path.exists(staged)
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0

def test_second_pending_request_refused(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, APAmendmentError
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'first request here', _fs()); db.session.commit()
    with pytest.raises(APAmendmentError):
        create_request(ap, admin_user, 'second request here', _fs())

def test_request_refused_when_not_incomplete(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, approve_request, APAmendmentError
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived', _fs()); db.session.commit()
    approve_request(req, admin_user); db.session.commit()   # slot now filled
    with pytest.raises(APAmendmentError):
        create_request(ap, admin_user, 'another signed copy', _fs())

def test_withdraw_discards_staged_file_and_marks_withdrawn(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, withdraw_request, _staged_dir
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    assert os.path.exists(staged)
    withdraw_request(req, admin_user); db.session.commit()
    assert req.status == 'withdrawn'
    assert not os.path.exists(staged)

def test_withdraw_refused_for_other_staff(client, db_session, admin_user, staff_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, withdraw_request, APAmendmentError
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    with pytest.raises(APAmendmentError):
        withdraw_request(req, staff_user)   # not the requester, not approver-level

def test_approve_autorejects_when_slot_already_filled(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request, approve_request, APAmendmentError, _staged_dir
    from app.accounts_payable.models import AccountsPayableAttachment
    from app.utils import ph_now
    import os
    ap = _posted_incomplete_ap(db_session, main_branch)
    req = create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    # Fill the required slot through another path before approval:
    db.session.add(AccountsPayableAttachment(
        ap_id=ap.id, original_filename='other.pdf', stored_filename='other-x.pdf',
        mime_type='application/pdf', file_size=5, uploaded_by_id=admin_user.id,
        kind='signed_ap', uploaded_at=ph_now()))
    db.session.commit()
    with pytest.raises(APAmendmentError):
        approve_request(req, admin_user)
    db.session.refresh(req)
    assert req.status == 'rejected'
    assert not os.path.exists(staged)
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id, kind='signed_ap').count() == 1

def _login(client, username='admin', password='admin123', branch=None):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    if branch is not None:
        with client.session_transaction() as s:
            s['selected_branch_id'] = branch.id

def test_route_request_then_approve_commits(client, db_session, admin_user, main_branch):
    from app.accounts_payable.models import AccountsPayableAttachment
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    r = client.post(f'/accounts-payable/{ap.id}/request-amendment',
                    data={'reason': 'signed copy arrived late',
                          'attachment': (io.BytesIO(b'%PDF-1.4'), 'signed.pdf')},
                    content_type='multipart/form-data')
    assert r.status_code in (302, 200)
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req
    req = Req.query.filter_by(ap_id=ap.id).first()
    assert req is not None and req.is_pending
    r = client.post(f'/accounts-payable/amendment-requests/{req.id}/approve', follow_redirects=True)
    assert r.status_code == 200
    db_session.refresh(req)
    assert req.status == 'approved'
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id, kind='signed_ap').count() == 1

def test_route_reject_leaves_ap_untouched(client, db_session, admin_user, main_branch):
    from app.accounts_payable.models import AccountsPayableAttachment
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    client.post(f'/accounts-payable/{ap.id}/request-amendment',
                data={'reason': 'wrong file here', 'attachment': (io.BytesIO(b'%PDF-1.4'), 'x.pdf')},
                content_type='multipart/form-data')
    req = Req.query.filter_by(ap_id=ap.id).first()
    client.post(f'/accounts-payable/amendment-requests/{req.id}/reject',
                data={'note': 'not the signed AP'}, follow_redirects=True)
    db_session.refresh(req)
    assert req.status == 'rejected'
    assert AccountsPayableAttachment.query.filter_by(ap_id=ap.id).count() == 0

def test_detail_shows_request_control_when_posted_incomplete(client, db_session, admin_user, main_branch):
    ap = _posted_incomplete_ap(db_session, main_branch)
    _login(client, branch=main_branch)
    body = client.get(f'/accounts-payable/{ap.id}').get_data(as_text=True)
    assert 'request-amendment' in body        # the request form action is present
    assert 'Signed AP' in body                # names the missing required file

def test_detail_shows_pending_then_approve_control(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    _login(client, branch=main_branch)
    body = client.get(f'/accounts-payable/{ap.id}').get_data(as_text=True)
    assert '/approve' in body and '/reject' in body    # approver review controls

def test_pending_request_appears_in_approval_items_and_count(client, db_session, admin_user, main_branch):
    from app.accounts_payable.amendment_service import create_request
    from app.dashboard.action_items_service import gather_approval_items, count_action_items
    ap = _posted_incomplete_ap(db_session, main_branch)
    create_request(ap, admin_user, 'signed copy arrived late', _fs()); db.session.commit()
    items = gather_approval_items(admin_user)
    assert any('AP-AMEND-1' in (i.get('id') or '') and 'Signed AP' in (i.get('desc') or '')
               for i in items)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    # count is branch-scoped; call the same way the sidebar does
    assert count_action_items(admin_user, main_branch.id) >= 1
