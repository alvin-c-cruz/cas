"""
Audit Log Views
Viewing audit trail for accountants and administrators
"""
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
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
    from datetime import datetime, timedelta
    from app.branches.models import Branch

    # Get filter parameters
    module_filter = request.args.get('module', '')
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user', '')
    branch_filter = request.args.get('branch', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    search_query = request.args.get('search', '')
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

    if branch_filter:
        query = query.filter_by(branch_id=int(branch_filter))

    # Date range filtering
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.timestamp >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            # Add 1 day to include the entire end date
            to_date = to_date + timedelta(days=1)
            query = query.filter(AuditLog.timestamp < to_date)
        except ValueError:
            pass

    # Full-text search across record_identifier and notes
    if search_query:
        query = query.filter(
            db.or_(
                AuditLog.record_identifier.ilike(f'%{search_query}%'),
                AuditLog.notes.ilike(f'%{search_query}%')
            )
        )

    # Order by timestamp descending (newest first)
    query = query.order_by(AuditLog.timestamp.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    # Get unique values for filters - dynamically from database
    modules = db.session.query(AuditLog.module).distinct().order_by(AuditLog.module).all()
    modules = [m[0] for m in modules]

    actions = db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
    actions = [a[0] for a in actions]

    users = User.query.order_by(User.username).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()

    # Get categories for grouping
    categories = list(set([log.get_action_category() for log in AuditLog.query.limit(100).all()]))

    return render_template('audit/audit_log.html',
                         logs=logs,
                         pagination=pagination,
                         modules=modules,
                         actions=actions,
                         users=users,
                         branches=branches,
                         module_filter=module_filter,
                         action_filter=action_filter,
                         user_filter=user_filter,
                         branch_filter=branch_filter,
                         date_from=date_from,
                         date_to=date_to,
                         search_query=search_query)
