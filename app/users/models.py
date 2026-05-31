from app import db
from app.utils import ph_now
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json


class LoginHistory(db.Model):
    """Login history model for audit trail."""
    __tablename__ = 'login_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    username = db.Column(db.String(80), nullable=False)  # Stored for record even if user deleted
    full_name = db.Column(db.String(200), nullable=False)
    login_time = db.Column(db.DateTime, default=ph_now, nullable=False)
    ip_address = db.Column(db.String(45))  # IPv4 or IPv6
    user_agent = db.Column(db.String(500))  # Browser/device info
    status = db.Column(db.String(20), nullable=False)  # 'success' or 'failed'
    failure_reason = db.Column(db.String(200))  # Reason if failed

    # Relationship
    user = db.relationship('User', backref=db.backref('login_history', lazy='dynamic'))

    def __repr__(self):
        return f'<LoginHistory {self.username} at {self.login_time}>'

    def to_dict(self):
        """Convert login history to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'full_name': self.full_name,
            'login_time': self.login_time.isoformat() if self.login_time else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'status': self.status,
            'failure_reason': self.failure_reason
        }


class User(UserMixin, db.Model):
    """User model for authentication and user management."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')  # 'admin', 'accountant', 'staff', 'viewer'
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Branch assignment (for accountant and staff roles)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)

    # Book permissions (JSON field to store which books user can access)
    # Stores: {"journal_entries": true, "accounts_receivable": true, ...}
    book_permissions = db.Column(db.Text, default='{}')

    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    last_login = db.Column(db.DateTime)

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

    def get_book_permissions(self):
        """Get book permissions as a dictionary."""
        try:
            return json.loads(self.book_permissions) if self.book_permissions else {}
        except:
            return {}

    def set_book_permissions(self, permissions_dict):
        """Set book permissions from a dictionary."""
        self.book_permissions = json.dumps(permissions_dict)

    def has_book_access(self, book_name):
        """Check if user has access to a specific book."""
        # Admins have access to all books
        if self.role == 'admin':
            return True

        # Check specific permissions
        permissions = self.get_book_permissions()
        return permissions.get(book_name, False)

    def __repr__(self):
        return f'<User {self.username}>'

    def to_dict(self):
        """Convert user to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
