"""
Notification model for user notifications
"""
from app import db
from app.utils import ph_now


class Notification(db.Model):
    """User notifications for change request outcomes and other events"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', backref='notifications')

    # Notification content
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # 'success', 'info', 'warning', 'error'

    # Notification metadata
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    read_at = db.Column(db.DateTime)

    # Optional: link to related object
    related_type = db.Column(db.String(50))  # 'vat_category_request', 'withholding_tax_request', etc.
    related_id = db.Column(db.Integer)

    def __repr__(self):
        return f'<Notification {self.id}: {self.title} for User {self.user_id}>'
