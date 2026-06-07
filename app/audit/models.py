"""
Audit Log Models
Tracks all changes to critical data in the system
"""
from app import db
from app.utils import ph_now

class AuditLog(db.Model):
    """
    Comprehensive audit trail for all system activities.

    Supported Action Types:
    - CRUD: 'create', 'update', 'delete'
    - Auth: 'login_success', 'login_failed', 'logout', 'session_timeout'
    - Security: 'account_locked', 'account_unlocked', 'password_changed', 'password_reset'
    - Access: 'branch_selected', 'branch_switched', 'unauthorized_access'
    - Assignment: 'branch_assigned', 'branch_removed', 'permission_granted', 'permission_revoked'
    - Approval: 'email_approved', 'email_deleted', 'registration_success', 'registration_failed'
    """
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)

    # What was changed
    module = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'user', 'branch', 'auth', 'email_approval'
    action = db.Column(db.String(30), nullable=False, index=True)  # See action types above
    record_id = db.Column(db.Integer, nullable=True)  # ID of the affected record (null for failed operations)
    record_identifier = db.Column(db.String(200))  # Human-readable identifier (name, code, username, etc.)

    # Who made the change
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Null for failed logins, system events
    user = db.relationship('User', backref='audit_logs')

    # Where the change was made (branch context)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)  # Null for system-level actions
    branch = db.relationship('Branch', backref='audit_logs')

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

    def get_action_category(self):
        """Get the category of this audit action."""
        crud_actions = ['create', 'update', 'delete']
        auth_actions = ['login_success', 'login_failed', 'logout', 'session_timeout']
        security_actions = ['account_locked', 'account_unlocked', 'password_changed', 'password_reset']
        access_actions = ['branch_selected', 'branch_switched', 'unauthorized_access']
        assignment_actions = ['branch_assigned', 'branch_removed', 'permission_granted', 'permission_revoked']
        approval_actions = ['email_approved', 'email_deleted', 'registration_success', 'registration_failed']

        if self.action in crud_actions:
            return 'CRUD'
        elif self.action in auth_actions:
            return 'Authentication'
        elif self.action in security_actions:
            return 'Security'
        elif self.action in access_actions:
            return 'Access'
        elif self.action in assignment_actions:
            return 'Assignment'
        elif self.action in approval_actions:
            return 'Approval'
        else:
            return 'Other'

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        import json
        return {
            'id': self.id,
            'module': self.module,
            'action': self.action,
            'category': self.get_action_category(),
            'record_id': self.record_id,
            'record_identifier': self.record_identifier,
            'user': self.user.username if self.user else None,
            'user_id': self.user_id,
            'branch': self.branch.name if self.branch else None,
            'branch_id': self.branch_id,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'old_values': json.loads(self.old_values) if self.old_values else None,
            'new_values': json.loads(self.new_values) if self.new_values else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'notes': self.notes
        }
