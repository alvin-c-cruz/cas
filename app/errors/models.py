"""
Error Log Models
Tracks all errors and exceptions that occur in the system
"""
from app import db
from app.utils import ph_now


class ErrorLog(db.Model):
    """
    Comprehensive error tracking for debugging and audit purposes.

    Stores critical errors that occur in the application with full context:
    - What error occurred (type, message, stack trace)
    - When it occurred (timestamp)
    - Who was affected (user)
    - Where it occurred (request URL, module)
    - How to reproduce (request data)
    """
    __tablename__ = 'error_logs'

    id = db.Column(db.Integer, primary_key=True)

    # When
    timestamp = db.Column(db.DateTime, default=ph_now, nullable=False, index=True)

    # What
    severity = db.Column(db.String(20), nullable=False, index=True)  # ERROR, CRITICAL
    module = db.Column(db.String(50), index=True)  # Module/endpoint where error occurred
    error_type = db.Column(db.String(100))  # Exception class name
    error_message = db.Column(db.Text)  # Exception message
    stack_trace = db.Column(db.Text)  # Full stack trace

    # Who
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship('User', foreign_keys=[user_id], backref='error_logs')

    # Where (Request context)
    request_url = db.Column(db.String(500))
    request_method = db.Column(db.String(10))  # GET, POST, etc.
    request_data = db.Column(db.Text)  # Form data (sanitized)
    ip_address = db.Column(db.String(45))  # IPv4 or IPv6
    user_agent = db.Column(db.String(500))  # Browser/client info

    # Resolution tracking
    is_resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id], backref='resolved_errors')
    resolution_notes = db.Column(db.Text)

    def __repr__(self):
        return f'<ErrorLog {self.id}: {self.error_type} at {self.timestamp}>'

    def to_dict(self):
        """Convert error log to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'severity': self.severity,
            'module': self.module,
            'error_type': self.error_type,
            'error_message': self.error_message,
            'user': self.user.username if self.user else 'Anonymous',
            'request_url': self.request_url,
            'request_method': self.request_method,
            'is_resolved': self.is_resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by': self.resolved_by.username if self.resolved_by else None
        }

    def mark_resolved(self, resolved_by_user, notes=None):
        """Mark this error as resolved."""
        self.is_resolved = True
        self.resolved_at = ph_now()
        self.resolved_by_id = resolved_by_user.id
        if notes:
            self.resolution_notes = notes
        db.session.commit()
