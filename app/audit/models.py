"""
Audit Log Models
Tracks all changes to critical data in the system
"""
from app import db
from app.utils import ph_now

class AuditLog(db.Model):
    """Comprehensive audit trail for all data modifications"""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)

    # What was changed
    module = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'customer', 'vendor', 'vat_category'
    action = db.Column(db.String(20), nullable=False, index=True)  # 'create', 'update', 'delete'
    record_id = db.Column(db.Integer, nullable=False)  # ID of the affected record
    record_identifier = db.Column(db.String(200))  # Human-readable identifier (name, code, etc.)

    # Who made the change
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', backref='audit_logs')

    # When the change was made
    timestamp = db.Column(db.DateTime, default=ph_now, nullable=False, index=True)

    # What changed (JSON)
    old_values = db.Column(db.Text)  # JSON string of old values (for update/delete)
    new_values = db.Column(db.Text)  # JSON string of new values (for create/update)

    # Additional context
    ip_address = db.Column(db.String(45))  # IPv4 or IPv6
    user_agent = db.Column(db.String(500))  # Browser/client info
    notes = db.Column(db.Text)  # Optional notes about the change

    def __repr__(self):
        return f'<AuditLog {self.module}.{self.action} by {self.user_id} at {self.timestamp}>'

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        import json
        return {
            'id': self.id,
            'module': self.module,
            'action': self.action,
            'record_id': self.record_id,
            'record_identifier': self.record_identifier,
            'user': self.user.username if self.user else None,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'old_values': json.loads(self.old_values) if self.old_values else None,
            'new_values': json.loads(self.new_values) if self.new_values else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'notes': self.notes
        }
