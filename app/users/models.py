from app import db
from app.utils import ph_now
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json


# Junction table for many-to-many relationship between users and branches
user_branches = db.Table('user_branches',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('branch_id', db.Integer, db.ForeignKey('branches.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=ph_now)
)


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

    # Branch assignment (DEPRECATED - kept for migration compatibility)
    # Use branches relationship instead for multiple branch assignments
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)

    # Many-to-many relationship with branches
    branches = db.relationship('Branch', secondary=user_branches,
                               backref=db.backref('users', lazy='dynamic'),
                               lazy='dynamic')

    # Book permissions (JSON field to store which books user can access)
    # Stores: {"journal_entries": true, "accounts_receivable": true, ...}
    book_permissions = db.Column(db.Text, default='{}')

    created_at = db.Column(db.DateTime, default=ph_now)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    last_login = db.Column(db.DateTime)

    # Account lockout fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_failed_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

    def is_account_locked(self):
        """Check if account is currently locked."""
        if self.account_locked_until is None:
            return False

        # Handle timezone-aware vs naive datetime comparison
        locked_until = self.account_locked_until
        if locked_until.tzinfo is None:
            # Database returns naive datetime, make it timezone-aware (PHT)
            from datetime import timezone, timedelta
            PHT = timezone(timedelta(hours=8))
            locked_until = locked_until.replace(tzinfo=PHT)

        return locked_until > ph_now()

    def increment_failed_attempts(self, max_attempts=5, lockout_minutes=15):
        """
        Increment failed login attempts and lock account if threshold exceeded.

        Args:
            max_attempts: Maximum allowed failed attempts before lockout (default: 5)
            lockout_minutes: Duration of lockout in minutes (default: 15)

        Returns:
            bool: True if account is now locked, False otherwise
        """
        from datetime import timedelta

        self.failed_login_attempts += 1
        self.last_failed_login = ph_now()

        if self.failed_login_attempts >= max_attempts:
            self.account_locked_until = ph_now() + timedelta(minutes=lockout_minutes)
            return True  # Account is now locked

        return False

    def reset_failed_attempts(self):
        """Reset failed login attempts after successful login."""
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.last_failed_login = None

    def unlock_account(self):
        """Manually unlock account (admin action)."""
        self.failed_login_attempts = 0
        self.account_locked_until = None

    def get_book_permissions(self):
        """Get book permissions as a dictionary."""
        try:
            return json.loads(self.book_permissions) if self.book_permissions else {}
        except:
            return {}

    def set_book_permissions(self, permissions_dict):
        """Set book permissions from a dictionary."""
        self.book_permissions = json.dumps(permissions_dict)

    @property
    def is_admin(self):
        """True only for the system administrator role (the 4 sysadmin areas)."""
        return self.role == 'admin'

    @property
    def has_full_access(self):
        """Admin OR Chief Accountant — full accounting reach across all branches.
        Used for branches, module access, approvals, periods, audit, year-end.
        Does NOT grant the 4 system-administration areas (those stay is_admin)."""
        return self.role in ('admin', 'chief_accountant')

    def has_book_access(self, book_name):
        """Check if user has access to a specific book."""
        # Admins have access to all books
        if self.role == 'admin':
            return True

        # Check specific permissions
        permissions = self.get_book_permissions()
        return permissions.get(book_name, False)

    def get_branch_ids(self):
        """Get list of branch IDs user is assigned to."""
        return [branch.id for branch in self.branches]

    def has_branch_access(self, branch_id):
        """Check if user has access to a specific branch."""
        # Admins have access to all branches
        if self.role == 'admin':
            return True

        # Check if user is assigned to this branch
        return branch_id in self.get_branch_ids()

    def add_branch(self, branch):
        """Add a branch to user's assignments."""
        if branch not in self.branches:
            self.branches.append(branch)

    def remove_branch(self, branch):
        """Remove a branch from user's assignments."""
        if branch in self.branches:
            self.branches.remove(branch)

    def set_branches(self, branch_list):
        """Set user's branch assignments from a list of Branch objects."""
        self.branches = branch_list

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
