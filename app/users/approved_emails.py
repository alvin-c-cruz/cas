"""
Approved Email model for controlling user registration access.

Only email addresses pre-approved by administrators can be used for registration.

Status lifecycle:
  pending   — submitted by an accountant, awaiting admin decision
  approved  — approved (by admin direct-add or after review); eligible to register
  rejected  — rejected by admin; cannot register
"""
from app import db
from app.utils import ph_now


class ApprovedEmail(db.Model):
    """
    Model for pre-approved email addresses that can register.

    Workflow:
    1. Admin adds email address to approved list (status='approved', immediate)
       — OR —
       Accountant requests an email (status='pending'), admin approves/rejects
    2. User with an *approved* email can register
    3. After registration, email is marked as 'used'
    4. Email cannot be reused for another registration
    """
    __tablename__ = 'approved_emails'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)

    # --- Status lifecycle ---
    status = db.Column(db.String(20), nullable=False, default='approved')
    # 'pending' | 'approved' | 'rejected'

    # Who submitted this row (null for legacy/direct admin adds)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # When the admin reviewed it (null until approved/rejected)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # Status tracking
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    notes = db.Column(db.Text, nullable=True)  # Admin notes about this approval

    # Relationships
    requested_by = db.relationship('User', foreign_keys=[requested_by_user_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_user_id], backref='emails_approved')
    used_by = db.relationship('User', foreign_keys=[used_by_user_id], backref='approved_email_used')

    def __repr__(self):
        status = "Used" if self.is_used else self.status
        return f'<ApprovedEmail {self.email} - {status}>'

    def mark_as_used(self, user_id):
        """Mark this email as used by a specific user."""
        self.is_used = True
        self.used_by_user_id = user_id
        self.used_at = ph_now()
        db.session.commit()

    def approve(self, reviewer_id):
        """Approve a pending request (admin action).

        Sets status='approved', records the reviewer and review timestamp.
        """
        self.status = 'approved'
        self.approved_by_user_id = reviewer_id
        self.reviewed_at = ph_now()
        db.session.commit()

    def reject(self, reviewer_id, reason):
        """Reject a pending request (admin action).

        Sets status='rejected', records the reviewer, review timestamp, and
        appends *reason* to the notes field.
        """
        self.status = 'rejected'
        self.approved_by_user_id = reviewer_id
        self.reviewed_at = ph_now()
        if reason:
            existing = self.notes or ''
            self.notes = (existing + '\nRejection reason: ' + reason).strip()
        db.session.commit()

    @staticmethod
    def is_email_approved(email):
        """
        Check if an email is pre-approved and available for registration.

        Only rows with status='approved' (and not yet used) pass this gate.
        pending/rejected rows return False.

        Returns:
            True if email is approved (status='approved') and not yet used
            False otherwise
        """
        approved = ApprovedEmail.query.filter_by(
            email=email.lower(), is_used=False, status='approved'
        ).first()
        return approved is not None

    @staticmethod
    def get_approved_email(email):
        """Get the ApprovedEmail record for a given email (status-agnostic lookup)."""
        return ApprovedEmail.query.filter_by(email=email.lower()).first()
