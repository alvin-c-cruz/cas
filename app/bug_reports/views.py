"""Bug report routes (spec: app-docs/superpowers/specs/2026-10-15-bug-reports-design.md, beside the
checkout). POST /bug-reports takes a report from any signed-in user; the /admin/bug-reports pages
belong to the system administrator."""
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from app import csrf
from app.bug_reports import service
from app.utils import ph_now

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
