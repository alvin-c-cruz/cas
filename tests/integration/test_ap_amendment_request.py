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
    v = Vendor(code='APV9', name='Amend Vendor', check_payee_name='Amend Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v); db_session.commit()
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-AMEND-1',
                         ap_date=date(2026, 9, 16), due_date=date(2026, 10, 16),
                         vendor_id=v.id, vendor_name=v.name, status='posted',
                         total_amount=Decimal('100'), notes='')
    db_session.add(ap); db_session.commit()
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
