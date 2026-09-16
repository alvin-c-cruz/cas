"""Attachments-only amendment workflow for a posted AP. Staff ask; approvers
commit the file. No financial change to the posted voucher — the approve path
only adds an AccountsPayableAttachment (kind='signed_ap')."""
import os
import uuid

from flask import current_app

from app import db
from app.utils import ph_now
from app.audit.utils import log_create
from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as Req


class APAmendmentError(ValueError):
    """Precondition failure surfaced to the user as a flash, never a 500."""


def _staged_dir(req_id):
    path = os.path.join(current_app.config['UPLOAD_FOLDER'],
                        'ap_amendment_requests', str(req_id))
    os.makedirs(path, exist_ok=True)
    return path


def pending_request_for(ap_id):
    return (Req.query
            .filter_by(ap_id=ap_id, status=Req.STATUS_PENDING)
            .order_by(Req.id.desc()).first())


def pending_requests_for_branches(branch_ids):
    if not branch_ids:
        return []
    return (Req.query
            .filter(Req.status == Req.STATUS_PENDING, Req.branch_id.in_(branch_ids))
            .order_by(Req.id.desc()).all())


def _missing_required_keys(ap):
    from app.attachments.completeness import missing_required
    return {s.key for s in missing_required('accounts_payable', ap)}


def create_request(ap, user, reason, file_storage):
    """Stage a file against a posted, incomplete AP. Adds to session; caller commits."""
    from app.accounts_payable.views import _ATTACHMENT_ALLOWED
    from werkzeug.utils import secure_filename

    reason = (reason or '').strip()
    if len(reason) < Req.MIN_REASON_LEN:
        raise APAmendmentError('Give a reason of at least %d characters — it becomes the '
                               'permanent record of why this posted AP was completed.'
                               % Req.MIN_REASON_LEN)
    if ap.status not in ('posted', 'partially_paid', 'paid'):
        raise APAmendmentError('Only a posted AP can have an attachment amendment request.')
    missing = _missing_required_keys(ap)
    if 'signed_ap' not in missing:
        raise APAmendmentError('This AP is not missing any required file.')
    if pending_request_for(ap.id) is not None:
        raise APAmendmentError('This AP already has an amendment request awaiting review.')

    original_name = secure_filename(file_storage.filename or '')
    if not original_name:
        raise APAmendmentError('Invalid filename.')
    _, ext = os.path.splitext(original_name); ext = ext.lower()
    mime_type = _ATTACHMENT_ALLOWED.get(ext)
    if mime_type is None:
        raise APAmendmentError('File type "%s" is not allowed. Accepted: %s'
                               % (ext or 'unknown', ', '.join(sorted(_ATTACHMENT_ALLOWED))))

    req = Req(ap_id=ap.id, branch_id=ap.branch_id, requested_by_id=user.id,
              reason=reason, kind='signed_ap',
              staged_original_filename=original_name,
              staged_stored_filename='',        # set after we know the id
              staged_mime_type=mime_type, staged_file_size=0)
    db.session.add(req)
    db.session.flush()                          # assigns req.id

    stored_name = uuid.uuid4().hex + ext
    path = os.path.join(_staged_dir(req.id), stored_name)
    file_storage.save(path)
    req.staged_stored_filename = stored_name
    req.staged_file_size = os.path.getsize(path)
    return req


def withdraw_request(req, user):
    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    if req.requested_by_id != user.id and not (user.has_full_access or user.role == 'accountant'):
        raise APAmendmentError('Only the requester or an approver can withdraw this request.')
    _delete_staged(req)
    req.status = Req.STATUS_WITHDRAWN
    return req


def reject_request(req, approver, note=None):
    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    _delete_staged(req)
    req.status = Req.STATUS_REJECTED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    req.review_note = (note or '').strip() or None
    return req


def approve_request(req, approver):
    """Commit the staged file into the AP as an AccountsPayableAttachment. Adds to
    session and commits (mirrors _save_ap_attachment's own-commit). Returns the row."""
    from app.accounts_payable.models import AccountsPayable, AccountsPayableAttachment
    from app.accounts_payable.views import _ap_upload_dir

    if not req.is_pending:
        raise APAmendmentError('This request has already been %s.' % req.status)
    ap = db.session.get(AccountsPayable, req.ap_id)
    if ap is None or ap.status not in ('posted', 'partially_paid', 'paid'):
        raise APAmendmentError('This AP can no longer take an attachment amendment.')
    # Authoritative re-check: the slot must still be empty at commit time.
    if req.kind not in _missing_required_keys(ap):
        _delete_staged(req)
        req.status = Req.STATUS_REJECTED
        req.reviewed_by_id = approver.id; req.reviewed_at = ph_now()
        req.review_note = 'Already completed before approval.'
        db.session.commit()
        raise APAmendmentError('The required file was already added; nothing to approve.')

    staged = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    dest_name = uuid.uuid4().hex + os.path.splitext(req.staged_original_filename)[1].lower()
    dest = os.path.join(_ap_upload_dir(ap.id), dest_name)
    import shutil
    shutil.copyfile(staged, dest)

    att = AccountsPayableAttachment(
        ap_id=ap.id, original_filename=req.staged_original_filename,
        stored_filename=dest_name, mime_type=req.staged_mime_type,
        file_size=req.staged_file_size, uploaded_by_id=req.requested_by_id, kind=req.kind)
    db.session.add(att)
    req.status = Req.STATUS_APPROVED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    db.session.commit()

    log_create(module='accounts_payable_attachment', record_id=att.id,
               record_identifier='%s / %s' % (ap.ap_number, att.original_filename),
               new_values={'ap_id': ap.id, 'kind': att.kind,
                           'original_filename': att.original_filename,
                           'via': 'amendment_request', 'request_id': req.id})
    _delete_staged(req)
    return att


def _delete_staged(req):
    if not req.staged_stored_filename:
        return
    path = os.path.join(_staged_dir(req.id), req.staged_stored_filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            current_app.logger.warning('Could not remove staged AP amendment file: %s', path)
