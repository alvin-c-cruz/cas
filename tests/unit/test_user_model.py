"""
Unit tests for User model
"""
import pytest
from app.users.models import User


@pytest.mark.unit
@pytest.mark.models
class TestUserModel:
    """Test User model functionality"""

    def test_create_user(self, db_session):
        """Test creating a new user"""
        user = User(
            username='testuser',
            email='test@example.com',
            full_name='Test User',
            role='staff'
        )
        user.set_password('password123')

        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.username == 'testuser'
        assert user.email == 'test@example.com'
        assert user.role == 'staff'
        assert user.is_active is True  # Default value

    def test_password_hashing(self, db_session):
        """Test password hashing and verification"""
        user = User(username='testuser', email='test@example.com', full_name='Test User')
        user.set_password('password123')

        db_session.add(user)
        db_session.commit()

        # Password should be hashed
        assert user.password_hash != 'password123'
        assert user.password_hash.startswith('scrypt:')

        # Should verify correct password
        assert user.check_password('password123') is True

        # Should not verify incorrect password
        assert user.check_password('wrongpassword') is False

    def test_user_repr(self, admin_user):
        """Test user string representation"""
        assert repr(admin_user) == '<User admin>'

    def test_user_roles(self, db_session):
        """Test different user roles"""
        roles = ['admin', 'accountant', 'staff', 'viewer']

        for role in roles:
            user = User(
                username=f'{role}_user',
                email=f'{role}@test.com',
                full_name=f'{role.title()} User',
                role=role
            )
            user.set_password('test123')
            db_session.add(user)

        db_session.commit()

        # Verify all users were created with correct roles
        for role in roles:
            user = User.query.filter_by(role=role).first()
            assert user is not None
            assert user.role == role

    def test_user_is_active_default(self, db_session):
        """Test that is_active defaults to True"""
        user = User(
            username='activeuser',
            email='active@test.com',
            full_name='Active User',
            role='staff'
        )
        user.set_password('TestPass1!')
        db_session.add(user)
        db_session.commit()

        assert user.is_active is True

    def test_deactivate_user(self, staff_user):
        """Test deactivating a user"""
        staff_user.is_active = False
        assert staff_user.is_active is False

    def test_unique_username(self, db_session, admin_user):
        """Test that username must be unique"""
        with pytest.raises(Exception):  # Should raise IntegrityError
            duplicate_user = User(
                username='admin',  # Same as admin_user
                email='different@test.com',
                full_name='Different User',
                role='staff'
            )
            duplicate_user.set_password('test123')
            db_session.add(duplicate_user)
            db_session.commit()

    def test_unique_email(self, db_session, admin_user):
        """Test that email must be unique"""
        with pytest.raises(Exception):  # Should raise IntegrityError
            duplicate_user = User(
                username='different',
                email='admin@test.com',  # Same as admin_user
                full_name='Different User',
                role='staff'
            )
            duplicate_user.set_password('test123')
            db_session.add(duplicate_user)
            db_session.commit()
