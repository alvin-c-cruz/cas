"""
Account Change Request model for approval workflow
"""
from app import db
from app.utils import ph_now
import json


class AccountChangeRequest(db.Model):
    """
    Tracks pending changes to Chart of Accounts requiring approval.

    Workflow:
    1. Accountant creates/edits/deletes an account -> creates a change request
    2. Another accountant must approve the change
    3. If only one accountant exists, they can self-approve
    4. Upon approval, the change is applied to the Account table
    """
    __tablename__ = 'account_change_requests'

    id = db.Column(db.Integer, primary_key=True)

    # Change type: 'create', 'update', 'delete'
    change_type = db.Column(db.String(20), nullable=False)

    # For update/delete: reference to existing account
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)

    # JSON data containing the proposed changes
    # For 'create': all new account fields
    # For 'update': only changed fields
    # For 'delete': account data for audit trail
    change_data = db.Column(db.Text, nullable=False)

    # Requestor (who requested the change)
    requested_by = db.Column(db.String(100), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    # Approval status: 'pending', 'approved', 'rejected'
    status = db.Column(db.String(20), default='pending', nullable=False)

    # Approver (who approved/rejected)
    reviewed_by = db.Column(db.String(100))
    reviewed_at = db.Column(db.DateTime)

    # Rejection reason (if rejected)
    rejection_reason = db.Column(db.Text)

    # Relationship to account (for update/delete)
    account = db.relationship('Account', backref='change_requests', foreign_keys=[account_id])

    def __repr__(self):
        return f'<AccountChangeRequest {self.change_type} - {self.status}>'

    def get_change_data(self):
        """Parse JSON change data"""
        return json.loads(self.change_data) if self.change_data else {}

    def set_change_data(self, data):
        """Store data as JSON"""
        self.change_data = json.dumps(data)

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'change_type': self.change_type,
            'account_id': self.account_id,
            'change_data': self.get_change_data(),
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'rejection_reason': self.rejection_reason
        }

    def can_be_approved_by(self, username):
        """
        Check if a user can approve this request.

        Rules:
        - User must be accountant or admin
        - User cannot approve their own request (unless they're the only accountant)
        """
        from app.users.models import User

        # Get total number of accountants (including admins who can act as accountants)
        total_accountants = User.query.filter(
            User.role.in_(['accountant', 'admin']),
            User.is_active == True
        ).count()

        # If only one accountant, allow self-approval
        if total_accountants == 1:
            return True

        # Otherwise, cannot approve own request
        return username != self.requested_by
