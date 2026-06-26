"""
Error Viewing and Management Routes
Admin interface for viewing and resolving system errors
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.errors.models import ErrorLog
from app.errors.utils import get_error_summary
from datetime import datetime, timedelta

errors_bp = Blueprint('errors', __name__, template_folder='templates')


def admin_required(f):
    """Decorator to require admin role"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@errors_bp.route('/admin/errors')
@login_required
@admin_required
def list_errors():
    """
    List all errors with filtering and pagination.

    Query parameters:
    - severity: Filter by ERROR or CRITICAL
    - module: Filter by module name
    - resolved: Filter by resolution status (0=unresolved, 1=resolved)
    - days: Show errors from last N days (default: 7)
    - page: Page number for pagination
    """
    # Get filter parameters
    severity = request.args.get('severity', '')
    module = request.args.get('module', '')
    resolved_filter = request.args.get('resolved', '')
    days = int(request.args.get('days', 7))
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Build query
    query = ErrorLog.query

    # Apply filters
    if severity:
        query = query.filter_by(severity=severity)

    if module:
        query = query.filter_by(module=module)

    if resolved_filter:
        is_resolved = resolved_filter == '1'
        query = query.filter_by(is_resolved=is_resolved)

    # Filter by date range
    if days > 0:
        since_date = datetime.now() - timedelta(days=days)
        query = query.filter(ErrorLog.timestamp >= since_date)

    # Order by most recent first
    query = query.order_by(ErrorLog.timestamp.desc())

    # Paginate
    errors = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get summary statistics
    summary = get_error_summary()

    # Get unique modules for filter dropdown
    modules = db.session.query(ErrorLog.module).distinct().all()
    modules = [m[0] for m in modules if m[0]]

    return render_template('errors/list.html',
                         errors=errors,
                         summary=summary,
                         modules=modules,
                         filters={
                             'severity': severity,
                             'module': module,
                             'resolved': resolved_filter,
                             'days': days
                         })


@errors_bp.route('/admin/errors/<int:id>')
@login_required
@admin_required
def view_error(id):
    """View detailed information about a specific error."""
    error = db.get_or_404(ErrorLog, id)
    return render_template('errors/detail.html', error=error)


@errors_bp.route('/admin/errors/<int:id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_error(id):
    """Mark an error as resolved."""
    error = db.get_or_404(ErrorLog, id)

    resolution_notes = request.form.get('resolution_notes', '').strip()

    if not error.is_resolved:
        error.mark_resolved(current_user, resolution_notes)
        flash(f'Error #{id} marked as resolved.', 'success')
    else:
        flash(f'Error #{id} is already resolved.', 'info')

    return redirect(url_for('errors.view_error', id=id))


@errors_bp.route('/admin/errors/<int:id>/unresolve', methods=['POST'])
@login_required
@admin_required
def unresolve_error(id):
    """Mark a resolved error as unresolved (reopen)."""
    error = db.get_or_404(ErrorLog, id)

    if error.is_resolved:
        error.is_resolved = False
        error.resolved_at = None
        error.resolved_by_id = None
        error.resolution_notes = None
        db.session.commit()
        flash(f'Error #{id} reopened.', 'success')
    else:
        flash(f'Error #{id} is not resolved.', 'info')

    return redirect(url_for('errors.view_error', id=id))


@errors_bp.route('/admin/errors/dashboard')
@login_required
@admin_required
def dashboard():
    """Error statistics dashboard."""
    summary = get_error_summary()

    # Get errors by day (last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_errors = ErrorLog.query.filter(
        ErrorLog.timestamp >= thirty_days_ago
    ).all()

    # Group by date
    errors_by_date = {}
    for error in recent_errors:
        date_key = error.timestamp.date()
        if date_key not in errors_by_date:
            errors_by_date[date_key] = {'total': 0, 'critical': 0, 'error': 0}
        errors_by_date[date_key]['total'] += 1
        if error.severity == 'CRITICAL':
            errors_by_date[date_key]['critical'] += 1
        else:
            errors_by_date[date_key]['error'] += 1

    # Get recent unresolved errors
    recent_unresolved = ErrorLog.query.filter_by(
        is_resolved=False
    ).order_by(ErrorLog.timestamp.desc()).limit(10).all()

    return render_template('errors/dashboard.html',
                         summary=summary,
                         errors_by_date=errors_by_date,
                         recent_unresolved=recent_unresolved)
