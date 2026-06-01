"""
Audit Log Views
Viewing audit trail for accountants and administrators
"""
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from functools import wraps
from app.audit.models import AuditLog
from app.users.models import User

audit_bp = Blueprint('audit', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            from flask import redirect, url_for
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            from flask import flash
            flash('Only Accountants and Administrators can view audit logs.', 'error')
            from flask import redirect, url_for
            return redirect(url_for('dashboard.home'))
        return f(*args, **kwargs)
    return decorated_function


@audit_bp.route('/audit-log')
@login_required
@accountant_or_admin_required
def audit_log():
    """View audit log with filtering"""
    # Get filter parameters
    module_filter = request.args.get('module', '')
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Build query
    query = AuditLog.query

    if module_filter:
        query = query.filter_by(module=module_filter)

    if action_filter:
        query = query.filter_by(action=action_filter)

    if user_filter:
        query = query.filter_by(user_id=int(user_filter))

    # Order by timestamp descending (newest first)
    query = query.order_by(AuditLog.timestamp.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    # Get unique values for filters
    modules = ['customer', 'vendor', 'vat_category', 'withholding_tax', 'user']
    actions = ['create', 'update', 'delete']
    users = User.query.filter(User.role.in_(['accountant', 'admin'])).all()

    return render_template('audit/audit_log.html',
                         logs=logs,
                         pagination=pagination,
                         modules=modules,
                         actions=actions,
                         users=users,
                         module_filter=module_filter,
                         action_filter=action_filter,
                         user_filter=user_filter)
