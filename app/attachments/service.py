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


def save_attachment(target, doc, file_storage, user, kind=None):
    """Validate and persist ONE uploaded file. Returns (True, None) or
    (False, message). Never raises for a bad file: rolls back and removes any
    written file, so the caller can skip it and go on.

    *kind* is the named slot the file fills (e.g. 'signed_pr'); None for an
    unlabeled "Other" file. The caller validates it against the target's slots;
    an unknown kind is stored as-is only if the caller passes it, so views
    normalise unknown kinds to None first.

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
            kind=kind or None,
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
                'kind': kind or None,
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
    """Everything attachments/_panel.html needs, computed once per render.

    Builds a per-slot checklist: each visible slot with the files in it and
    whether it is filled, plus an "Other" bucket for unlabeled files and any
    file whose kind is no longer a visible slot (e.g. a slot later hidden).
    """
    from app.attachments.completeness import visible_slots, required_slots, approved_incomplete

    atts = attachments_for(target.document_type, doc.id)
    upload_ok = can_upload(target, doc, user)
    deletable = {a.id for a in atts if can_delete(target, doc, user, a)}

    slots = visible_slots(target.document_type, doc)
    required_keys = {s.key for s in required_slots(target.document_type, doc)}
    slot_keys = {s.key for s in slots}

    by_kind = {}
    for a in atts:
        by_kind.setdefault(a.kind, []).append(a)

    slot_rows = []
    for slot in slots:
        files = by_kind.get(slot.key, [])
        slot_rows.append({
            'key': slot.key,
            'label': slot.label,
            'required': slot.key in required_keys,
            'files': files,
            'filled': bool(files),
        })
    # "Other": kind is None, or kind not among the currently visible slots.
    other_files = [a for a in atts if not a.kind or a.kind not in slot_keys]

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
        'slot_rows': slot_rows,
        'other_files': other_files,
        'missing_required_count': sum(1 for r in slot_rows if r['required'] and not r['filled']),
        'missing_required_labels': [r['label'] for r in slot_rows if r['required'] and not r['filled']],
        'approved_incomplete_count': len(approved_incomplete(target.document_type, doc)),
        'can_upload': upload_ok,
        'deletable_ids': deletable,
        'closed_note': closed_note,
        'accept': ACCEPT_ATTR,
        'next_url': next_url,
    }


def record_approval_completeness(document_type, doc):
    """Soft gate: snapshot the required slots that are empty at approval/post time
    onto ``doc.approved_incomplete_slots`` (JSON list, or None when complete) and
    return the list of missing slot keys.

    Sets the attribute only; it does NOT commit -- the caller's approval commit
    persists it in the same transaction, so the marker can never disagree with
    the status. Returns [] when nothing is missing.
    """
    import json
    from app.attachments.completeness import missing_required
    missing = [s.key for s in missing_required(document_type, doc)]
    doc.approved_incomplete_slots = json.dumps(missing) if missing else None
    return missing


def missing_slot_labels(document_type, missing_keys):
    """Human labels for a list of slot keys, for flash/audit messages."""
    from app.attachments.registry import slots_for
    by_key = {s.key: s.label for s in slots_for(document_type)}
    return [by_key.get(k, k) for k in missing_keys]
