"""Persistence for shared document attachments: disk + row + audit, one file at
a time, each committed on its own so one bad file never blocks the rest.

Mirrors app/accounts_payable/views.py::_save_ap_attachment, which is the
pattern that already ships for AP vouchers.
"""
import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from app import db
from app.attachments.models import DocumentAttachment
from app.attachments.registry import can_delete, can_upload
from app.audit.utils import log_create, log_delete

# Server-side allowlist: extension -> canonical MIME type. The stored MIME type
# comes from HERE, never from the client. SVG is intentionally excluded: it
# executes script when served inline.
ALLOWED_TYPES = {
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.webp': 'image/webp',
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':  'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.csv':  'text/csv',
    '.txt':  'text/plain',
}

#: For the <input accept=...> hint on forms. The server allowlist is the gate.
ACCEPT_ATTR = ','.join(sorted(ALLOWED_TYPES))


def upload_dir(document_type, document_id):
    """instance/uploads/<document_type>/<document_id>/, created on demand."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], document_type, str(document_id))
    os.makedirs(path, exist_ok=True)
    return path


def file_path(attachment):
    """The one place that knows the on-disk layout."""
    return os.path.join(current_app.config['UPLOAD_FOLDER'],
                        attachment.document_type, str(attachment.document_id),
                        attachment.stored_filename)


def attachments_for(document_type, document_id):
    return (DocumentAttachment.query
            .filter_by(document_type=document_type, document_id=document_id)
            .order_by(DocumentAttachment.uploaded_at, DocumentAttachment.id)
            .all())


def save_attachment(target, doc, file_storage, user):
    """Validate and persist ONE uploaded file. Returns (True, None) or
    (False, message). Never raises for a bad file: rolls back and removes any
    written file, so the caller can skip it and go on.

    Does NOT check the status/role gate -- the route does that once for the
    whole request, and the create-form hook runs on a document that was just
    created as a draft by a user who passed the module's own gate.
    """
    original_name = secure_filename(file_storage.filename or '')
    if not original_name:
        return False, 'Invalid filename.'

    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = ALLOWED_TYPES.get(ext)
    if mime_type is None:
        allowed = ', '.join(sorted(ALLOWED_TYPES))
        return False, f'File type "{ext or "unknown"}" is not allowed. Accepted: {allowed}'

    stored_name = uuid.uuid4().hex + ext
    path = os.path.join(upload_dir(target.document_type, doc.id), stored_name)
    try:
        file_storage.save(path)
        file_size = os.path.getsize(path)

        attachment = DocumentAttachment(
            document_type=target.document_type,
            document_id=doc.id,
            original_filename=original_name,
            stored_filename=stored_name,
            mime_type=mime_type,
            file_size=file_size,
            uploaded_by_id=user.id,
        )
        db.session.add(attachment)
        db.session.commit()

        log_create(
            module=f'{target.document_type}_attachment',
            record_id=attachment.id,
            record_identifier=f'{target.number(doc)} / {original_name}',
            new_values={
                'document_type': target.document_type,
                'document_id': doc.id,
                'original_filename': original_name,
                'stored_filename': stored_name,
                'mime_type': mime_type,
                'file_size': file_size,
            },
        )
        return True, None
    except Exception:  # noqa: BLE001 - any failure must leave no half-saved file
        db.session.rollback()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        current_app.logger.error('Error saving %s attachment', target.document_type,
                                 exc_info=True)
        return False, 'An unexpected error occurred while saving the file.'


def save_queued_attachments(target, doc, files, user):
    """Create-form hook: persist every file queued on the form. Empty entries
    are ignored. Returns the ORIGINAL names of the files that were skipped so
    the caller can flash one warning."""
    skipped = []
    for f in files or ():
        if not f or not f.filename:
            continue
        ok, _err = save_attachment(target, doc, f, user)
        if not ok:
            skipped.append(f.filename)
    return skipped


def delete_attachment(target, doc, attachment, user):
    """Row first, then file, then audit. A file already missing from disk is
    logged, not fatal: the row is the record and it is gone either way."""
    path = file_path(attachment)
    old_values = {
        'document_type': attachment.document_type,
        'document_id': attachment.document_id,
        'original_filename': attachment.original_filename,
        'stored_filename': attachment.stored_filename,
        'mime_type': attachment.mime_type,
        'file_size': attachment.file_size,
    }
    identifier = f'{target.number(doc)} / {attachment.original_filename}'
    attachment_id = attachment.id

    db.session.delete(attachment)
    db.session.commit()

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            current_app.logger.warning('Could not remove attachment file: %s', path)

    log_delete(
        module=f'{target.document_type}_attachment',
        record_id=attachment_id,
        record_identifier=identifier,
        old_values=old_values,
        notes=f'Deleted by {user.username}',
    )


def panel_context(target, doc, user, next_url=None):
    """Everything attachments/_panel.html needs, computed once per render."""
    atts = attachments_for(target.document_type, doc.id)
    upload_ok = can_upload(target, doc, user)
    deletable = {a.id for a in atts if can_delete(target, doc, user, a)}
    if upload_ok:
        closed_note = None
    elif target.amend_statuses and doc.status in target.amend_statuses:
        closed_note = ('Uploads are closed for this document. An approver can '
                       'add further files through Amend.')
    else:
        closed_note = 'Uploads are closed: this document has been approved.'
    return {
        'document_type': target.document_type,
        'document': doc,
        'attachments': atts,
        'can_upload': upload_ok,
        'deletable_ids': deletable,
        'closed_note': closed_note,
        'accept': ACCEPT_ATTR,
        'next_url': next_url,
    }
