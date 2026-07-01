"""Pre-printed voucher forms — designer backend (P-69 Task 4).

Blueprint for the pre-printed-form designer: the admin toggle list, the
designer page (Task 5 fleshes out the template/JS), and the save/upload/toggle
routes that persist a `PrintLayout` per voucher type.

Permission model (blueprint-enforced; the registry auto-gate in
`app/users/module_access.py` does NOT apply here — these endpoints aren't
listed in MODULE_REGISTRY):
    _module_required  -> instance flag only (module_enabled('preprinted_forms'))
    _edit_required    -> instance flag AND (full access OR accountant OR
                          staff with an explicit print_layouts grant;
                          viewers never, regardless of grant)
    _admin_required   -> instance flag AND current_user.is_admin
"""
import json
import os
import uuid
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, send_file, abort, session
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from flask import Response

from app import db
from app.preprinted_forms.models import PrintLayout, VOUCHER_TYPES, VOUCHER_LABELS
from app.preprinted_forms.field_catalog import FIELD_CATALOG
from app.preprinted_forms.pdf import render_preprinted
from app.users.module_access import module_enabled
from app.audit.utils import log_audit

preprinted_forms_bp = Blueprint('preprinted_forms', __name__, template_folder='templates')

# voucher type -> model class providing the "most recent record" for test-print.
# Imported lazily inside test_print() to avoid import-order issues at blueprint
# import time (these blueprints all import app.db too).
_TEST_PRINT_MODEL_NAMES = {
    'SI': ('app.sales_invoices.models', 'SalesInvoice'),
    'CR': ('app.cash_receipts.models', 'CashReceiptVoucher'),
    'CD': ('app.cash_disbursements.models', 'CashDisbursementVoucher'),
    'AP': ('app.accounts_payable.models', 'AccountsPayable'),
    'JV': ('app.journal_entries.models', 'JournalEntry'),
}

# Server-side allowlist: extension -> canonical MIME type. SVG excluded (executes
# JS when served inline) — mirrors app/company_settings/views.py's logo chain.
_IMAGE_ALLOWED = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}
_IMAGE_MAX_BYTES = 2 * 1024 * 1024  # ~2 MB


def _module_required(f):
    """Instance-level package gate only — for read-only routes that don't need
    per-user edit rights (e.g. the admin toggle list)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not module_enabled('preprinted_forms'):
            flash('The pre-printed forms module is not enabled.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def _edit_required(f):
    """Instance flag AND per-user grant (full access, accountant, or staff via
    the explicit print_layouts book permission; viewers never)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not module_enabled('preprinted_forms'):
            flash('The pre-printed forms module is not enabled.', 'error')
            return redirect(url_for('dashboard.index'))
        if not (current_user.has_full_access or current_user.role == 'accountant'
                or (current_user.role == 'staff' and current_user.has_book_access('print_layouts'))):
            flash('You do not have permission to design pre-printed forms.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def _admin_required(f):
    """Instance flag AND admin role — used only for the toggle route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not module_enabled('preprinted_forms'):
            flash('The pre-printed forms module is not enabled.', 'error')
            return redirect(url_for('dashboard.index'))
        if not current_user.is_admin:
            flash('Only administrators can enable pre-printed forms.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def _validate_voucher_type(vt):
    if vt not in VOUCHER_TYPES:
        abort(404)


def _get_or_create_layout(vt):
    layout = PrintLayout.query.filter_by(voucher_type=vt).first()
    if layout is None:
        layout = PrintLayout(voucher_type=vt)
        db.session.add(layout)
        db.session.flush()
    return layout


def _upload_dir():
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'preprinted')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_json_string(raw, default):
    """Round-trip `raw` through json.loads/dumps so a malformed post can never
    persist un-parseable JSON into fields_json/line_band_json. Falls back to
    `default` (already a JSON string) on parse failure."""
    try:
        json.loads(raw)
        return raw
    except (TypeError, ValueError):
        return default


@preprinted_forms_bp.route('/preprinted-forms')
@login_required
@_module_required
def admin():
    """List the 5 voucher types with their pre-printed active/inactive toggle."""
    layouts = {l.voucher_type: l for l in PrintLayout.query.all()}
    return render_template('preprinted_forms/admin_toggles.html',
                            voucher_types=VOUCHER_TYPES, voucher_labels=VOUCHER_LABELS,
                            layouts=layouts)


@preprinted_forms_bp.route('/preprinted-forms/<vt>/design')
@login_required
@_edit_required
def designer(vt):
    _validate_voucher_type(vt)
    layout = PrintLayout.query.filter_by(voucher_type=vt).first()
    catalog = FIELD_CATALOG.get(vt, {'header': [], 'line_columns': []})
    header_fields = [{'key': f['key'], 'label': f['label']} for f in catalog['header']]
    line_columns = [{'key': f['key'], 'label': f['label']} for f in catalog['line_columns']]
    page_width_mm = float(layout.page_width_mm) if layout else 215.90
    page_height_mm = float(layout.page_height_mm) if layout else 279.40
    return render_template(
        'preprinted_forms/designer.html', vt=vt, layout=layout,
        header_fields=header_fields, line_columns=line_columns,
        page_width_mm=page_width_mm, page_height_mm=page_height_mm,
        fields_json=(layout.fields_json if layout else '[]'),
        line_band_json=(layout.line_band_json if layout else '{}'),
        fields=(layout.get_fields() if layout else []),
        line_band=(layout.get_line_band() if layout else {}),
    )


@preprinted_forms_bp.route('/preprinted-forms/<vt>/test-print')
@login_required
@_edit_required
def test_print(vt):
    """Render the most recent record of this voucher type through the
    layout as a test PDF (background drawn for alignment). Redirects back
    to the designer with a flash if no record of the type exists yet."""
    _validate_voucher_type(vt)
    layout = _get_or_create_layout(vt)

    module_name, class_name = _TEST_PRINT_MODEL_NAMES[vt]
    module = __import__(module_name, fromlist=[class_name])
    model = getattr(module, class_name)

    # Branch-scope: without this, a branch-scoped accountant could render
    # another branch's most recent record (customer/TIN/amounts) since all
    # five models carry branch_id. Matches how document lists scope to the
    # selected branch.
    branch_id = session.get('selected_branch_id')
    query = model.query
    if branch_id:
        query = query.filter_by(branch_id=branch_id)
    record = query.order_by(model.id.desc()).first()
    if record is None:
        flash('Create a document first to test print.', 'warning')
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    pdf_bytes = render_preprinted(layout, record, test=True)
    return Response(pdf_bytes, mimetype='application/pdf',
                     headers={'Content-Disposition': 'inline; filename="test-print.pdf"'})


@preprinted_forms_bp.route('/preprinted-forms/<vt>/save', methods=['POST'])
@login_required
@_edit_required
def save(vt):
    _validate_voucher_type(vt)
    layout = _get_or_create_layout(vt)

    old_values = {'fields_json': layout.fields_json, 'line_band_json': layout.line_band_json}

    fields_json = _safe_json_string(request.form.get('fields_json', '[]'), layout.fields_json or '[]')
    line_band_json = _safe_json_string(request.form.get('line_band_json', '{}'), layout.line_band_json or '{}')

    layout.fields_json = fields_json
    layout.line_band_json = line_band_json
    layout.updated_by = current_user.username
    db.session.commit()

    log_audit(
        module='preprinted_forms', action='update', record_id=layout.id,
        record_identifier=vt, old_values=old_values,
        new_values={'fields_json': fields_json, 'line_band_json': line_band_json}
    )

    flash(f'{vt} pre-printed layout saved.', 'success')
    return redirect(url_for('preprinted_forms.designer', vt=vt))


@preprinted_forms_bp.route('/preprinted-forms/<vt>/image', methods=['POST'])
@login_required
@_edit_required
def upload_image(vt):
    """Upload (or replace) a voucher type's background reference image.
    Mirrors app/company_settings/views.py::upload_logo verbatim in spirit."""
    _validate_voucher_type(vt)

    uploaded_file = request.files.get('image')
    if not uploaded_file or uploaded_file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    original_name = secure_filename(uploaded_file.filename)
    if not original_name:
        flash('Invalid filename.', 'error')
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = _IMAGE_ALLOWED.get(ext)
    if mime_type is None:
        allowed = ', '.join(sorted(_IMAGE_ALLOWED))
        flash(f'File type "{ext or "unknown"}" is not allowed. Accepted: {allowed}', 'error')
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    # Size check (~2 MB max) without trusting Content-Length
    uploaded_file.stream.seek(0, os.SEEK_END)
    file_size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if file_size > _IMAGE_MAX_BYTES:
        flash('Image file is too large. Maximum size is 2 MB.', 'error')
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    # Magic-number check: file content must match the declared extension.
    header = uploaded_file.stream.read(12)
    uploaded_file.stream.seek(0)
    if ext == '.png':
        signature_ok = header.startswith(b'\x89PNG\r\n\x1a\n')
    else:  # .jpg / .jpeg
        signature_ok = header.startswith(b'\xff\xd8\xff')
    if not signature_ok:
        flash(
            f'File content does not match a valid {ext} image. '
            'Please upload a genuine PNG or JPEG file.', 'error'
        )
        return redirect(url_for('preprinted_forms.designer', vt=vt))

    stored_name = uuid.uuid4().hex + ext
    file_path = os.path.join(_upload_dir(), stored_name)

    layout = _get_or_create_layout(vt)
    old_image = layout.background_image

    try:
        uploaded_file.save(file_path)
        layout.background_image = stored_name
        layout.updated_by = current_user.username
        db.session.commit()

        if old_image and old_image != stored_name:
            old_path = os.path.join(_upload_dir(), old_image)
            try:
                if os.path.isfile(old_path):
                    os.remove(old_path)
            except OSError:
                current_app.logger.warning(
                    f'Could not delete old preprinted form image: {old_path}', exc_info=True
                )

        log_audit(
            module='preprinted_forms', action='update', record_id=layout.id,
            record_identifier=vt, old_values={'background_image': old_image},
            new_values={'background_image': stored_name},
            notes=f'Background image uploaded: {original_name} ({file_size} bytes)'
        )

        flash('Background image uploaded successfully!', 'success')
    except Exception:
        db.session.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        current_app.logger.error('Error uploading preprinted form image', exc_info=True)
        flash('An error occurred while uploading the image. Please try again.', 'error')

    return redirect(url_for('preprinted_forms.designer', vt=vt))


@preprinted_forms_bp.route('/preprinted-forms/<vt>/image', methods=['GET'])
@login_required
@_module_required
def image(vt):
    """Serve a voucher type's background reference image to any authenticated
    user whose instance has the module enabled (mirrors company logo serving)."""
    _validate_voucher_type(vt)
    layout = PrintLayout.query.filter_by(voucher_type=vt).first()
    if layout is None or not layout.background_image:
        abort(404)

    file_path = os.path.join(_upload_dir(), layout.background_image)
    if not os.path.isfile(file_path):
        abort(404)

    _, ext = os.path.splitext(layout.background_image)
    mime_type = _IMAGE_ALLOWED.get(ext.lower(), 'application/octet-stream')

    response = send_file(file_path, mimetype=mime_type, as_attachment=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@preprinted_forms_bp.route('/preprinted-forms/<vt>/toggle', methods=['POST'])
@login_required
@_admin_required
def toggle(vt):
    """Flip a voucher type's pre-printed `active` flag (admin only)."""
    _validate_voucher_type(vt)
    layout = _get_or_create_layout(vt)

    old_active = layout.active
    layout.active = not layout.active
    layout.updated_by = current_user.username
    db.session.commit()

    log_audit(
        module='preprinted_forms', action='update', record_id=layout.id,
        record_identifier=vt, old_values={'active': old_active},
        new_values={'active': layout.active}
    )

    flash(f'{vt} pre-printed form {"enabled" if layout.active else "disabled"}.', 'success')
    return redirect(url_for('preprinted_forms.admin'))
