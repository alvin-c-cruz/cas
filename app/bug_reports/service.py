"""Bug reports: validation, storage and clean-up. Ported from Sanay's src/server/reports.ts and
reports-http.ts (C:/envs/sanay); what changed for CAS is in the spec,
app-docs/superpowers/specs/2026-10-15-bug-reports-design.md beside the checkout."""
import base64
import binascii
import json
import os
import re
import subprocess
import uuid
from datetime import timedelta

from flask import current_app, session

from app import db
from app.audit.utils import log_audit, log_update
from app.bug_reports.models import BugReport, BugReportImage
from app.bug_reports.statuses import CLOSED_STATUSES, OPEN_STATUSES, is_closed
from app.utils import ph_now

LIMITS = {
    'body_bytes': 2_000_000,
    'message': 5000,
    'context_bytes': 64_000,
    'image_bytes': 400_000,
    'images': 2,
    'per_day': 10,
    'keep_pictures_days': 90,
}
EXTENSIONS = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}
_BASE64 = re.compile(r'[A-Za-z0-9+/]+={0,2}')


class ReportRejected(Exception):
    """A report the server refuses: `code` is the JSON error, `status` the HTTP status."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def sniff_mime(data):
    """JPEG, PNG or WebP, recognised by their first bytes; anything else is None."""
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def first_words(message):
    """The message on one line, cut at a word after 57 characters, for a notification."""
    line = ' '.join(message.split())
    return line if len(line) <= 60 else re.sub(r'\s+\S*$', '', line[:57]) + '…'


def parse_report(body):
    """Check a decoded JSON body. Returns (message, context, images), images being
    (kind, mime, bytes) with the mime sniffed from the bytes. The browser's own 'server' key is
    dropped: only the server writes it. Raises ReportRejected."""
    if not isinstance(body, dict):
        raise ReportRejected('bad_json')

    message = body.get('message')
    message = message.strip() if isinstance(message, str) else ''
    if not message or len(message) > LIMITS['message']:
        raise ReportRejected('bad_message')

    context = body.get('context')
    if not isinstance(context, dict):
        raise ReportRejected('bad_context')
    context = dict(context)
    context.pop('server', None)
    if len(json.dumps(context, ensure_ascii=False).encode('utf-8')) > LIMITS['context_bytes']:
        raise ReportRejected('context_too_large', 413)

    raw = body.get('images')
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > LIMITS['images']:
        raise ReportRejected('bad_images')
    images = []
    for im in raw:
        if not isinstance(im, dict) or im.get('kind') not in ('page', 'own'):
            raise ReportRejected('bad_image')
        data = im.get('data')
        if not isinstance(data, str) or not _BASE64.fullmatch(data):
            raise ReportRejected('bad_image')
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise ReportRejected('bad_image')
        if len(decoded) > LIMITS['image_bytes']:
            raise ReportRejected('image_too_large', 413)
        mime = sniff_mime(decoded)
        if mime is None:
            raise ReportRejected('bad_image')
        images.append((im['kind'], mime, decoded))
    return message, context, images


def _write_file(path, data):
    with open(path, 'wb') as f:
        f.write(data)


def report_dir(report_id):
    """Where a report's pictures live, beside the attachments (app/attachments/service.py)."""
    return os.path.join(current_app.config['UPLOAD_FOLDER'], 'bug_reports', str(report_id))


def reports_since(user_id, since):
    """How many reports this user has sent since `since` -- the daily limit."""
    return BugReport.query.filter(BugReport.user_id == user_id, BugReport.created_at >= since).count()


_VERSION = None


def app_version():
    """The git commit the server runs, asked once and cached; '' when git cannot say. With several
    clients on different commits, this is what identifies the code a report was sent from."""
    global _VERSION
    if _VERSION is None:
        try:
            out = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=os.path.dirname(current_app.root_path),
                                 capture_output=True, text=True, timeout=5)
            sha = out.stdout.strip()
            _VERSION = sha if out.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}', sha) else ''
        except (OSError, subprocess.SubprocessError):
            _VERSION = ''
    return _VERSION


def server_context(user):
    """What the server knows and the browser cannot be trusted to say. Needs a request: the
    branch is the session's."""
    from app.branches.models import Branch
    from app.settings import AppSettings

    branch_id = session.get('selected_branch_id')
    branch = db.session.get(Branch, branch_id) if branch_id else None
    return {
        'user': {'id': user.id, 'username': user.username, 'full_name': user.full_name, 'role': user.role},
        'branch': {'id': branch.id, 'name': branch.name} if branch else None,
        'company': AppSettings.get_setting('company_name') or '',
        'version': app_version(),
        'receivedAt': ph_now().isoformat(),
    }


def create_report(user, message, context, images, now):
    """Store a report, its pictures and one notification per active admin in ONE commit, then
    audit it. `images` is parse_report's list of (kind, mime, bytes). On any failure nothing stays
    behind: the session is rolled back and every file already written is deleted, so there is never
    a row whose file is missing or a file with no row. Returns the report id."""
    from app.notifications.models import Notification
    from app.users.models import User

    written, folder = [], None
    try:
        report = BugReport(user_id=user.id, message=message, created_at=now,
                           context=json.dumps(context, ensure_ascii=False))
        db.session.add(report)
        db.session.flush()
        if images:
            folder = report_dir(report.id)
            os.makedirs(folder, exist_ok=True)
        for kind, mime, data in images:
            name = f'{uuid.uuid4().hex}.{EXTENSIONS[mime]}'
            path = os.path.join(folder, name)
            written.append(path)
            _write_file(path, data)
            db.session.add(BugReportImage(report_id=report.id, kind=kind, mime=mime, stored_name=name,
                                          size_bytes=len(data), created_at=now))
        # CAS sends no email and shows no notifications yet; the rows wait for a notifications page.
        for admin in User.query.filter_by(role='admin', is_active=True).all():
            db.session.add(Notification(user_id=admin.id, title='Bug report',
                                        message=f'{user.full_name}: {first_words(message)}',
                                        category='info', related_type='bug_report', related_id=report.id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        for path in written:
            try:
                os.remove(path)
            except OSError:
                pass
        if folder:
            try:
                os.rmdir(folder)
            except OSError:
                pass
        raise
    log_audit('bug_report', 'create', report.id, record_identifier=f'Bug report #{report.id}',
              new_values={'message': first_words(message), 'images': len(images)}, user_id=user.id)
    return report.id


def new_report_count():
    """The sidebar badge."""
    return BugReport.query.filter_by(status='new').count()


def report_counts():
    open_n = BugReport.query.filter(BugReport.status.in_(OPEN_STATUSES)).count()
    closed_n = BugReport.query.filter(BugReport.status.in_(CLOSED_STATUSES)).count()
    return {'open': open_n, 'closed': closed_n, 'all': open_n + closed_n}


def reports_for(view):
    """Newest first (insertion order), 200 at most as in Sanay. `view` is open, closed or all."""
    query = BugReport.query
    if view == 'open':
        query = query.filter(BugReport.status.in_(OPEN_STATUSES))
    elif view == 'closed':
        query = query.filter(BugReport.status.in_(CLOSED_STATUSES))
    return query.order_by(BugReport.id.desc()).limit(200).all()


def related_errors(report):
    """Server errors for the same user from 30 minutes before the report to 1 minute after: a form
    that fails on save shows only the error page, so the stack trace is the evidence."""
    from app.errors.models import ErrorLog

    return (ErrorLog.query
            .filter(ErrorLog.user_id == report.user_id,
                    ErrorLog.timestamp >= report.created_at - timedelta(minutes=30),
                    ErrorLog.timestamp <= report.created_at + timedelta(minutes=1))
            .order_by(ErrorLog.timestamp.desc())
            .all())


def set_status(report, status, now):
    """A closed status keeps the first closing time; an open one clears it. Audited. The same
    status again changes nothing and returns False."""
    old = report.status
    if status == old:
        return False
    report.status = status
    report.closed_at = (report.closed_at or now) if is_closed(status) else None
    db.session.commit()
    log_update('bug_report', report.id, f'Bug report #{report.id}', {'status': old}, {'status': status})
    return True


def purge_old_pictures(now):
    """Delete the pictures of reports closed more than 90 days before `now`; the report stays.
    A file already gone is fine; a file that cannot be deleted keeps its row for the next try."""
    cutoff = now - timedelta(days=LIMITS['keep_pictures_days'])
    old = (BugReport.query
           .filter(BugReport.closed_at.isnot(None), BugReport.closed_at < cutoff, BugReport.images.any())
           .all())
    removed = 0
    for report in old:
        folder = report_dir(report.id)
        for image in list(report.images):
            path = os.path.join(folder, image.stored_name)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                current_app.logger.warning('bug report %s: could not delete %s: %s', report.id, path, e)
                continue
            report.images.remove(image)  # delete-orphan deletes the row
            removed += 1
        try:
            os.rmdir(folder)
        except OSError:
            pass
    if removed:
        db.session.commit()
    return removed
