"""Bug report routes (spec: app-docs/superpowers/specs/2026-10-15-bug-reports-design.md, beside the
checkout). POST /bug-reports takes a report from any signed-in user; the /admin/bug-reports pages
belong to the system administrator."""
import json
import os
from datetime import timedelta

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from app import csrf, db
from app.bug_reports import service
from app.bug_reports.models import BugReport, BugReportImage
from app.bug_reports.statuses import CLOSED_STATUSES, OPEN_STATUSES, STATUS_LABEL, is_closed, is_status
from app.utils import ph_now
from app.utils.authz import admin_panel_required

bug_reports_bp = Blueprint('bug_reports', __name__, template_folder='templates')


@bug_reports_bp.route('/bug-reports', methods=['POST'])
@csrf.exempt
def create():
    """A user's bug report. JSON in, JSON out, never a redirect: the browser follows a redirect and
    would read the page it lands on as success. So this route answers for itself where the
    app-wide handlers redirect -- signed out (login_required) and a bad CSRF token
    (csrf_error_handler, which also clears the session). The branch and password gates exempt it in
    create_app. Who sent it comes from the session, never from the body."""
    if not current_user.is_authenticated:
        return jsonify(error='signed_out'), 401
    if current_app.config.get('WTF_CSRF_ENABLED', True):
        try:
            validate_csrf(request.headers.get('X-CSRFToken'))
        except ValidationError:
            return jsonify(error='bad_csrf'), 400
    if (request.content_length or 0) > service.LIMITS['body_bytes']:
        return jsonify(error='too_large'), 413
    try:
        message, context, images = service.parse_report(request.get_json(silent=True))
    except service.ReportRejected as e:
        return jsonify(error=e.code), e.status

    now = ph_now()
    if service.reports_since(current_user.id, now - timedelta(days=1)) >= service.LIMITS['per_day']:
        return jsonify(error='too_many'), 429
    context['server'] = service.server_context(current_user)
    report_id = service.create_report(current_user, message, context, images, now)
    return jsonify(id=report_id), 201


@bug_reports_bp.route('/admin/bug-reports')
@login_required
@admin_panel_required
def list_reports():
    service.purge_old_pictures(ph_now())
    show = request.args.get('show')
    view = show if show in ('closed', 'all') else 'open'
    return render_template('bug_reports/list.html', reports=service.reports_for(view),
                           counts=service.report_counts(), view=view,
                           STATUS_LABEL=STATUS_LABEL, is_closed=is_closed)


@bug_reports_bp.route('/admin/bug-reports/<int:report_id>')
@login_required
@admin_panel_required
def view_report(report_id):
    report = db.get_or_404(BugReport, report_id)
    return render_template('bug_reports/detail.html', report=report,
                           context_json=json.dumps(report.context_data, indent=2, ensure_ascii=False),
                           errors=service.related_errors(report),
                           OPEN_STATUSES=OPEN_STATUSES, CLOSED_STATUSES=CLOSED_STATUSES,
                           STATUS_LABEL=STATUS_LABEL)


@bug_reports_bp.route('/admin/bug-reports/<int:report_id>/status', methods=['POST'])
@login_required
@admin_panel_required
def set_status(report_id):
    report = db.get_or_404(BugReport, report_id)
    status = request.form.get('status')
    if not is_status(status):
        flash('That is not a bug report status.', 'error')
    elif service.set_status(report, status, ph_now()):
        flash(f'Status changed to {STATUS_LABEL[status]}.', 'success')
    return redirect(url_for('bug_reports.view_report', report_id=report.id))


@bug_reports_bp.route('/admin/bug-reports/<int:report_id>/images/<int:image_id>')
@login_required
@admin_panel_required
def image(report_id, image_id):
    """The picture itself, never cached, under the attachment-preview policy
    (app/attachments/views.py). The path is built only from the server-generated name."""
    picture = BugReportImage.query.filter_by(id=image_id, report_id=report_id).first()
    if picture is None:
        abort(404)
    path = os.path.join(service.report_dir(report_id), picture.stored_name)
    if not os.path.isfile(path):
        abort(404)
    with open(path, 'rb') as f:
        data = f.read()
    response = Response(data, mimetype=picture.mime)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@bug_reports_bp.app_context_processor
def inject_bug_reports_new_count():
    """The sidebar badge: New reports, counted only for the system administrator."""
    if not (current_user.is_authenticated and current_user.is_admin):
        return {'bug_reports_new_count': 0}
    try:
        return {'bug_reports_new_count': service.new_report_count()}
    except Exception:  # an unmigrated database must not take every admin page down with it
        db.session.rollback()
        return {'bug_reports_new_count': 0}
