"""Routes for shared document attachments, plus the `attachment_panel` Jinja
global that detail/form pages call to render attachments/_panel.html.

Every route resolves the document through the registry and re-checks the
status/role gate itself; the panel merely reflects the same answer.
"""
import os

from flask import (abort, current_app, flash, redirect, request, send_file,
                   url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.attachments import attachments_bp
from app.attachments.models import DocumentAttachment
from app.attachments.registry import can_delete, can_upload, get_target
from app.attachments.service import (delete_attachment, file_path,
                                     panel_context, save_attachment)


def _resolve(document_type, document_id):
    """(target, doc) or 404 for an unknown type / missing row."""
    target = get_target(document_type)
    if target is None:
        abort(404)
    doc = target.load(document_id)
    if doc is None:
        abort(404)
    return target, doc


def _back(target, doc):
    """Where to go after an action: the caller's page if it named a safe
    relative one, else the document's detail page."""
    nxt = request.form.get('next') or request.args.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt:
        return redirect(nxt)
    return redirect(url_for(target.view_endpoint, id=doc.id))


@attachments_bp.route('/attachments/<document_type>/<int:document_id>/upload',
                      methods=['POST'])
@login_required
def upload(document_type, document_id):
    target, doc = _resolve(document_type, document_id)

    if not can_upload(target, doc, current_user):
        flash('Attachments can no longer be added to this document.', 'error')
        return _back(target, doc)

    files = [f for f in request.files.getlist('attachments') if f and f.filename]
    single = request.files.get('attachment')
    if single and single.filename:
        files.append(single)
    if not files:
        flash('No file selected.', 'error')
        return _back(target, doc)

    # Optional slot the files fill. Validate against this document's slots; an
    # unknown/blank kind is stored as an unlabeled "Other" (None).
    from app.attachments.registry import slots_for
    kind = (request.form.get('kind') or '').strip() or None
    if kind and kind not in {s.key for s in slots_for(document_type)}:
        kind = None

    saved, skipped = [], []
    for f in files:
        ok, err = save_attachment(target, doc, f, current_user, kind=kind)
        if ok:
            saved.append(secure_filename(f.filename))
        else:
            skipped.append(f'{secure_filename(f.filename) or f.filename}: {err}')

    if saved:
        flash(f'Uploaded {len(saved)} file{"s" if len(saved) != 1 else ""}: '
              + ', '.join(saved), 'success')
    for msg in skipped:
        flash(msg, 'error')
    return _back(target, doc)


@attachments_bp.route('/attachments/<int:attachment_id>/download')
@login_required
def download(attachment_id):
    attachment = db.get_or_404(DocumentAttachment, attachment_id)
    target, doc = _resolve(attachment.document_type, attachment.document_id)

    path = file_path(attachment)
    if not os.path.isfile(path):
        flash('File not found on disk.', 'error')
        return redirect(url_for(target.view_endpoint, id=doc.id))

    response = send_file(path, mimetype=attachment.mime_type, as_attachment=True,
                         download_name=attachment.original_filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@attachments_bp.route('/attachments/<int:attachment_id>/preview')
@login_required
def preview(attachment_id):
    """Serve a previewable attachment inline for the popup modal.

    Images go in an <img>, PDFs in an <iframe> rendered by the browser's own
    viewer. Office documents cannot render in a frame, so they 404 here and stay
    download-only. Every response carries X-Content-Type-Options: nosniff, and
    the stored mime type is the server-validated one (from the upload allowlist),
    so a file can never be reinterpreted as active HTML/JS.
    """
    attachment = db.get_or_404(DocumentAttachment, attachment_id)
    if not attachment.is_previewable:
        abort(404)
    _resolve(attachment.document_type, attachment.document_id)

    path = file_path(attachment)
    if not os.path.isfile(path):
        abort(404)

    # download_name keeps the disposition "inline" but gives the tab/viewer the
    # real filename.
    response = send_file(path, mimetype=attachment.mime_type, as_attachment=False,
                         download_name=attachment.original_filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if attachment.is_image:
        # Images need nothing but themselves; lock the context down completely.
        response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    else:
        # PDF: the browser's built-in viewer will not render under a bare
        # `sandbox` or a `default-src 'none'` policy, so restrict only who may
        # frame it. The file cannot be interpreted as anything but a PDF
        # (nosniff + the server-validated application/pdf type), and it carries
        # no active content of its own, so this is safe.
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
    return response


@attachments_bp.route('/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete(attachment_id):
    attachment = db.get_or_404(DocumentAttachment, attachment_id)
    target, doc = _resolve(attachment.document_type, attachment.document_id)

    if not can_delete(target, doc, current_user, attachment):
        flash('You cannot delete this attachment.', 'error')
        return _back(target, doc)

    name = attachment.original_filename
    delete_attachment(target, doc, attachment, current_user)
    flash(f'Attachment "{name}" deleted.', 'success')
    return _back(target, doc)


@attachments_bp.app_template_global('attachment_panel')
def attachment_panel(document_type, doc, next_url=None):
    """Called from a template as `{% set att = attachment_panel('purchase_orders', po) %}`
    right before `{% include 'attachments/_panel.html' %}`."""
    target = get_target(document_type)
    if target is None:
        raise ValueError(f'No attachment target registered for {document_type!r}')
    return panel_context(target, doc, current_user, next_url=next_url)


@attachments_bp.app_template_global('attachment_incomplete_count')
def attachment_incomplete_count(document_type, doc):
    """Badge helper: how many required slots this APPROVED/posted document was
    approved with, that are still empty. 0 when complete or not applicable, so a
    template can do `{% if attachment_incomplete_count('purchase_orders', po) %}`.
    Self-heals — returns 0 once the missing files are added. Works for AP too
    (document_type 'accounts_payable'), which is not a shared TARGET."""
    from app.attachments.completeness import approved_incomplete
    return len(approved_incomplete(document_type, doc))
