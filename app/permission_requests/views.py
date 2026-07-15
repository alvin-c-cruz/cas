"""Permission Change Request views."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_audit
from app.users.models import User
from app.users.module_access import all_permission_keys
from app.permission_requests.forms import PermissionRequestForm
from app.permission_requests.models import PermissionChangeRequest
from app.utils.authz import admin_panel_required

permission_requests_bp = Blueprint('permission_requests', __name__, template_folder='templates')


def chief_accountant_required(f):
    """Restrict to the Chief Accountant role -- the only role this feature's
    request-creation flow is for (admin already has the direct /users/<id>/edit path,
    so this decorator intentionally does NOT admit admin)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'chief_accountant':
            flash('Only Chief Accountants can request permission changes.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


def _valid_accountant_targets():
    return User.query.filter_by(role='accountant', is_active=True).order_by(User.username).all()


@permission_requests_bp.route('/permission-requests/new', methods=['GET', 'POST'])
@login_required
@chief_accountant_required
def new_permission_request():
    form = PermissionRequestForm()
    targets = _valid_accountant_targets()
    form.target_user_id.choices = [(u.id, f'{u.username} ({u.full_name})') for u in targets]
    form.requested_keys.choices = [(k, k) for k in all_permission_keys()]

    if form.validate_on_submit():
        target = db.session.get(User, form.target_user_id.data)
        if target is None or target.role != 'accountant' or not target.is_active:
            flash('Invalid target user.', 'error')
            return redirect(url_for('permission_requests.new_permission_request'))

        requested = {k: True for k in form.requested_keys.data if k in all_permission_keys()}
        if not requested:
            flash('No valid permission keys selected.', 'error')
            return redirect(url_for('permission_requests.new_permission_request'))

        existing = PermissionChangeRequest.query.filter_by(
            target_user_id=target.id, requested_by_id=current_user.id, status='pending'
        ).all()
        for req in existing:
            if req.get_requested_permissions() == requested:
                flash(f'You already have a pending request for {target.username} with these '
                      f'exact permissions.', 'error')
                return redirect(url_for('permission_requests.new_permission_request'))

        change_request = PermissionChangeRequest(
            target_user_id=target.id,
            requested_by_id=current_user.id,
            request_reason=form.request_reason.data,
            status='pending',
        )
        change_request.set_requested_permissions(requested)
        db.session.add(change_request)
        db.session.commit()

        log_audit(
            module='permission_change_request',
            action='create',
            record_id=change_request.id,
            record_identifier=f'{target.username} ({target.full_name})',
            new_values=requested,
            notes=f'Requested by {current_user.username}: {form.request_reason.data}'
        )
        flash('Permission change request submitted for admin approval.', 'success')
        return redirect(url_for('permission_requests.new_permission_request'))

    return render_template('permission_requests/new.html', form=form)


@permission_requests_bp.route('/permission-requests/pending')
@login_required
@admin_panel_required
def pending_permission_requests():
    pending_requests = PermissionChangeRequest.query.filter_by(status='pending').order_by(
        PermissionChangeRequest.created_at.desc()
    ).all()
    return render_template('permission_requests/pending.html', pending_requests=pending_requests)
