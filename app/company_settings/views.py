"""
Company Settings views (Admin only).

All values are stored as key-value rows in app_settings (AppSettings model) —
no dedicated model or migration.
"""
import os
import uuid
from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, send_file, abort
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.settings import AppSettings
from app.company_settings.forms import CompanySettingsForm
from app.audit.utils import log_audit
from app.utils.authz import admin_panel_required

company_settings_bp = Blueprint('company_settings', __name__, template_folder='templates')


# Settings keys managed by the form, in display order.
# Form field names match the app_settings keys exactly.
SETTINGS_KEYS = [
    'company_name',
    'trade_name',
    'company_tin',
    'tin_branch_code',
    'rdo_code',
    'vat_registration_type',
    'company_address',
    'postal_code',
    'phone',
    'email',
    'fiscal_year_start',
    'officer_president',
    'officer_treasurer',
    'officer_secretary',
    'apv_print_access',
    'sv_print_access',
    'sv_print_form',
    'cd_print_access',
    'cd_check_print_access',
    'cr_print_access',
    'cr_print_form',
]

LOGO_SETTING_KEY = 'company_logo'

# Server-side allowlist: extension → canonical MIME type.
# SVG is intentionally excluded — it executes JS when served inline.
_LOGO_ALLOWED = {
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
}

_LOGO_MAX_BYTES = 2 * 1024 * 1024  # ~2 MB


def _logo_upload_dir():
    """Return (and create if needed) the company logo upload directory."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'company')
    os.makedirs(path, exist_ok=True)
    return path


def _current_logo_filename():
    """Return the stored logo filename, or None when unset."""
    return AppSettings.get_setting(LOGO_SETTING_KEY) or None


def _delete_logo_file(stored_filename):
    """Remove a logo file from disk; never raise."""
    if not stored_filename:
        return
    file_path = os.path.join(_logo_upload_dir(), stored_filename)
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
    except OSError:
        current_app.logger.warning(
            f'Could not delete company logo file: {file_path}', exc_info=True
        )


@company_settings_bp.route('', methods=['GET', 'POST'])
@login_required
@admin_panel_required
def edit_settings():
    """View and update company-wide settings."""
    form = CompanySettingsForm()

    if form.validate_on_submit():
        try:
            old_values = {}
            new_values = {}

            for key in SETTINGS_KEYS:
                old_val = AppSettings.get_setting(key)
                new_val = (getattr(form, key).data or '').strip()

                if (old_val or '') == new_val:
                    continue

                AppSettings.set_setting(key, new_val, updated_by=current_user.username)
                old_values[key] = old_val
                new_values[key] = new_val

            # Boolean policy flag — handled outside the text-strip loop above.
            _sa_key = 'accountant_email_self_approval'
            _sa_old = AppSettings.get_setting(_sa_key, '0')
            _sa_new = '1' if form.accountant_email_self_approval.data else '0'
            if _sa_old != _sa_new:
                AppSettings.set_setting(_sa_key, _sa_new, updated_by=current_user.username)
                old_values[_sa_key] = _sa_old
                new_values[_sa_key] = _sa_new

            if new_values:
                log_audit(
                    module='settings',
                    action='update',
                    record_id=None,
                    record_identifier='company_settings',
                    old_values=old_values,
                    new_values=new_values
                )
                flash('Company settings saved successfully!', 'success')
            else:
                flash('No changes to save.', 'info')

            return redirect(url_for('company_settings.edit_settings'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error saving company settings', exc_info=True)
            flash('An error occurred while saving the settings. Please try again.', 'error')

    elif request.method == 'GET':
        # Populate form from stored settings
        for key in SETTINGS_KEYS:
            value = AppSettings.get_setting(key)
            if value:
                getattr(form, key).data = value

        form.accountant_email_self_approval.data = (
            AppSettings.get_setting('accountant_email_self_approval', '0') == '1')

    return render_template(
        'company_settings/form.html',
        form=form,
        logo_filename=_current_logo_filename()
    )


@company_settings_bp.route('/modules')
@login_required
@admin_panel_required
def modules():
    from app.users.module_access import MODULE_REGISTRY, module_enabled
    optional = [dict(m, enabled=module_enabled(m['key']))
                for m in MODULE_REGISTRY if m.get('optional')]
    return render_template('company_settings/modules.html', modules=optional)


@company_settings_bp.route('/modules/toggle', methods=['POST'])
@login_required
@admin_panel_required
def modules_toggle():
    from app.users.module_access import MODULE_REGISTRY, module_enabled, can_toggle
    from app.utils.cache_helpers import clear_module_config_cache
    key = request.form.get('key', '')
    enable = request.form.get('enable') == '1'
    enabled_keys = {m['key'] for m in MODULE_REGISTRY
                    if m.get('optional') and module_enabled(m['key'])}
    ok, reason = can_toggle(key, enable, enabled_keys)
    if not ok:
        flash(f'Cannot change "{key}": {reason}.', 'error')
        return redirect(url_for('company_settings.modules'))
    AppSettings.set_setting(f'module_enabled:{key}', '1' if enable else '0',
                            updated_by=current_user.username)
    clear_module_config_cache()
    log_audit(module='module_config', action='enable' if enable else 'disable',
              record_id=None, record_identifier=key,
              new_values={'enabled': enable})
    flash(f'Module "{key}" {"enabled" if enable else "disabled"}.', 'success')
    return redirect(url_for('company_settings.modules'))


@company_settings_bp.route('/logo/upload', methods=['POST'])
@login_required
@admin_panel_required
def upload_logo():
    """Upload (or replace) the company logo."""
    uploaded_file = request.files.get('logo')
    if not uploaded_file or uploaded_file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('company_settings.edit_settings'))

    original_name = secure_filename(uploaded_file.filename)
    if not original_name:
        flash('Invalid filename.', 'error')
        return redirect(url_for('company_settings.edit_settings'))

    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    mime_type = _LOGO_ALLOWED.get(ext)
    if mime_type is None:
        allowed = ', '.join(sorted(_LOGO_ALLOWED))
        flash(f'File type "{ext or "unknown"}" is not allowed. Accepted: {allowed}', 'error')
        return redirect(url_for('company_settings.edit_settings'))

    # Size check (~2 MB max) without trusting Content-Length
    uploaded_file.stream.seek(0, os.SEEK_END)
    file_size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if file_size > _LOGO_MAX_BYTES:
        flash('Logo file is too large. Maximum size is 2 MB.', 'error')
        return redirect(url_for('company_settings.edit_settings'))

    # Magic-number check: file content must match the declared extension.
    # The browser-supplied Content-Type is attacker-controlled, so we verify
    # the actual file signature instead.
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
        return redirect(url_for('company_settings.edit_settings'))

    stored_name = uuid.uuid4().hex + ext
    file_path = os.path.join(_logo_upload_dir(), stored_name)

    old_logo = _current_logo_filename()
    setting_committed = False

    try:
        uploaded_file.save(file_path)
        AppSettings.set_setting(LOGO_SETTING_KEY, stored_name, updated_by=current_user.username)
        setting_committed = True

        # Replacing a logo deletes the old file
        if old_logo and old_logo != stored_name:
            _delete_logo_file(old_logo)

        log_audit(
            module='settings',
            action='update',
            record_id=None,
            record_identifier='company_logo',
            old_values={LOGO_SETTING_KEY: old_logo},
            new_values={LOGO_SETTING_KEY: stored_name},
            notes=f'Logo uploaded: {original_name} ({file_size} bytes)'
        )

        flash('Company logo uploaded successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        if setting_committed:
            # set_setting already committed the new filename; restore the
            # previous value so the DB never references a missing file.
            try:
                if old_logo:
                    AppSettings.set_setting(
                        LOGO_SETTING_KEY, old_logo, updated_by=current_user.username
                    )
                else:
                    db.session.execute(db.delete(AppSettings).where(AppSettings.key == LOGO_SETTING_KEY))
                    db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.error(
                    'Failed to restore previous logo setting after upload error',
                    exc_info=True
                )
        if os.path.exists(file_path):
            os.remove(file_path)
        current_app.logger.error('Error uploading company logo', exc_info=True)
        flash('An error occurred while uploading the logo. Please try again.', 'error')

    return redirect(url_for('company_settings.edit_settings'))


@company_settings_bp.route('/logo/remove', methods=['POST'])
@login_required
@admin_panel_required
def remove_logo():
    """Remove the company logo (file + setting row)."""
    old_logo = _current_logo_filename()
    if not old_logo:
        flash('No company logo to remove.', 'info')
        return redirect(url_for('company_settings.edit_settings'))

    try:
        db.session.execute(db.delete(AppSettings).where(AppSettings.key == LOGO_SETTING_KEY))
        db.session.commit()
        _delete_logo_file(old_logo)

        log_audit(
            module='settings',
            action='delete',
            record_id=None,
            record_identifier='company_logo',
            old_values={LOGO_SETTING_KEY: old_logo},
            new_values={LOGO_SETTING_KEY: None},
            notes='Logo removed'
        )

        flash('Company logo removed.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error removing company logo', exc_info=True)
        flash('An error occurred while removing the logo. Please try again.', 'error')

    return redirect(url_for('company_settings.edit_settings'))


@company_settings_bp.route('/logo')
@login_required
def logo():
    """Serve the company logo to any authenticated user (used by the sidebar)."""
    stored_name = _current_logo_filename()
    if not stored_name:
        abort(404)

    file_path = os.path.join(_logo_upload_dir(), stored_name)
    if not os.path.isfile(file_path):
        abort(404)

    _, ext = os.path.splitext(stored_name)
    mime_type = _LOGO_ALLOWED.get(ext.lower(), 'application/octet-stream')

    response = send_file(file_path, mimetype=mime_type, as_attachment=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
