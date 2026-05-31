"""
Branch model for multi-branch accounting
"""
from app import db
from datetime import datetime


class Branch(db.Model):
    """Branch model for multi-branch support."""
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to users assigned to this branch
    users = db.relationship('User', backref='branch', lazy='dynamic')

    def __repr__(self):
        return f'<Branch {self.code} - {self.name}>'

    def to_dict(self):
        """Convert branch to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'address': self.address,
            'phone': self.phone,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'user_count': self.users.count()
        }
