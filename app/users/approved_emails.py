"""
Approved Email model for controlling user registration access.

Only email addresses pre-approved by administrators can be used for registration.
"""
from app import db
from app.utils import ph_now


class ApprovedEmail(db.Model):
    """
    Model for pre-approved email addresses that can register.

    Workflow:
    1. Admin adds email address to approved list
    2. User with that email can register
    3. After registration, email is marked as 'used'
    4. Email cannot be reused for another registration
    """
    __tablename__ = 'approved_emails'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)

    # Status tracking
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    # Metadata
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approved_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    notes = db.Column(db.Text, nullable=True)  # Admin notes about this approval

    # Relationships
    approved_by = db.relationship('User', foreign_keys=[approved_by_user_id], backref='emails_approved')
    used_by = db.relationship('User', foreign_keys=[used_by_user_id], backref='approved_email_used')

    def __repr__(self):
        status = "Used" if self.is_used else "Available"
        return f'<ApprovedEmail {self.email} - {status}>'

    def mark_as_used(self, user_id):
        """Mark this email as used by a specific user."""
        self.is_used = True
        self.used_by_user_id = user_id
        self.used_at = ph_now()
        db.session.commit()

    @staticmethod
    def is_email_approved(email):
        """
        Check if an email is pre-approved and available for registration.

        Returns:
            True if email is approved and not yet used
            False if email is not approved or already used
        """
        approved = ApprovedEmail.query.filter_by(email=email.lower(), is_used=False).first()
        return approved is not None

    @staticmethod
    def get_approved_email(email):
        """Get the ApprovedEmail record for a given email."""
        return ApprovedEmail.query.filter_by(email=email.lower()).first()
