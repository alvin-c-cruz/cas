"""Permission Change Request views."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app.users.models import User
from app.users.module_access import all_permission_keys
from app.permission_requests.forms import PermissionRequestForm

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
    return render_template('permission_requests/new.html', form=form)
