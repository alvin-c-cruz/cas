"""Bug reports sent from the "Report a problem" button (app/static/js/bug-report.js).

Pictures are files under UPLOAD_FOLDER/bug_reports/<report id>/, as attachments are; a row here
only names one. No branch_id: a bug report is not an accounting record (the branch is in the
context), and a branch_id would make the mapper-derived branch-delete guard refuse branch deletes
over bug reports.
"""
import json

from app import db
from app.utils import ph_now


class BugReport(db.Model):
    __tablename__ = 'bug_reports'
    __table_args__ = (db.Index('ix_bug_reports_user_created', 'user_id', 'created_at'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_bug_reports_user_id'),
                        nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='new', index=True)  # statuses.py
    closed_at = db.Column(db.DateTime)
    message = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text, nullable=False)  # JSON: where / before / device, plus server

    user = db.relationship('User', foreign_keys=[user_id])
    images = db.relationship('BugReportImage', backref='report', cascade='all, delete-orphan',
                             order_by='BugReportImage.id')

    @property
    def context_data(self):
        try:
            data = json.loads(self.context or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def page_path(self):
        where = self.context_data.get('where')
        return where.get('path') if isinstance(where, dict) else None

    def __repr__(self):
        return f'<BugReport {self.id} {self.status}>'


class BugReportImage(db.Model):
    __tablename__ = 'bug_report_images'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer,
                          db.ForeignKey('bug_reports.id', name='fk_bug_report_images_report_id'),
                          nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)          # page | own
    mime = db.Column(db.String(20), nullable=False)          # sniffed from the bytes, never the browser's claim
    stored_name = db.Column(db.String(100), nullable=False)  # server-generated file name
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    def __repr__(self):
        return f'<BugReportImage {self.id} of report {self.report_id}>'
