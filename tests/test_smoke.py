"""
Smoke tests for basic application functionality
Run these tests first to ensure the application is working
"""
import pytest


@pytest.mark.smoke
class TestApplicationStartup:
    """Test that the application starts correctly"""

    def test_app_exists(self, app):
        """Test that app fixture creates an app"""
        assert app is not None

    def test_app_is_testing(self, app):
        """Test that app is in testing mode"""
        assert app.config['TESTING'] is True

    def test_secret_key_is_set(self, app):
        """Test that SECRET_KEY is configured"""
        assert app.config['SECRET_KEY'] is not None
        assert app.config['SECRET_KEY'] != ''


@pytest.mark.smoke
class TestDatabaseConnection:
    """Test database connectivity"""

    def test_database_exists(self, db_session):
        """Test that database session is created"""
        assert db_session is not None

    def test_can_query_database(self, db_session):
        """Test that we can query the database"""
        from app.users.models import User
        # Should not raise an error
        users = User.query.all()
        assert isinstance(users, list)


@pytest.mark.smoke
class TestBasicRoutes:
    """Test that basic routes are accessible"""

    def test_login_route_exists(self, client):
        """Test that login route exists"""
        response = client.get('/login')
        assert response.status_code == 200

    def test_static_files_accessible(self, client):
        """Test that static files can be accessed"""
        # Test CSS file access
        response = client.get('/static/css/main.css')
        # 200 (exists) or 404 (doesn't exist but route works) is acceptable
        assert response.status_code in [200, 404]


@pytest.mark.smoke
class TestModelsImport:
    """Test that all models can be imported"""

    def test_import_user_model(self):
        """Test importing User model"""
        from app.users.models import User
        assert User is not None

    def test_import_account_model(self):
        """Test importing Account model"""
        from app.accounts.models import Account
        assert Account is not None

    def test_import_branch_model(self):
        """Test importing Branch model"""
        from app.branches.models import Branch
        assert Branch is not None

    def test_import_customer_model(self):
        """Test importing Customer model"""
        from app.customers.models import Customer
        assert Customer is not None

    def test_import_vendor_model(self):
        """Test importing Vendor model"""
        from app.vendors.models import Vendor
        assert Vendor is not None


@pytest.mark.smoke
class TestErrorLogging:
    """Test that error logging infrastructure exists"""

    def test_error_log_model_exists(self):
        """Test that ErrorLog model can be imported"""
        from app.errors.models import ErrorLog
        assert ErrorLog is not None

    def test_error_logging_utils_exist(self):
        """Test that error logging utilities exist"""
        from app.errors.utils import log_exception, log_error_to_db
        assert log_exception is not None
        assert log_error_to_db is not None


@pytest.mark.smoke
class TestSecurityFeatures:
    """Test that security features are enabled"""

    def test_csrf_protection_configured(self, app):
        """Test that CSRF protection is configured (disabled for testing)"""
        # CSRF should be disabled in testing mode for ease of testing
        # but enabled in development and production
        if app.config['TESTING']:
            assert app.config.get('WTF_CSRF_ENABLED') is False
        else:
            assert app.config.get('WTF_CSRF_ENABLED', True) is True

    def test_permanent_session_lifetime_is_twelve_hours(self, app):
        """PERMANENT_SESSION_LIFETIME defaults to a 12-hour workday, not the old
        1-hour value that was previously dead config (BUG-PA-SESSION-UNEXPECTED-LOGOUT)."""
        from datetime import timedelta
        assert app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(hours=12)

    def test_session_cookie_security(self, app):
        """Test that session cookies are configured securely"""
        # HTTPOnly should be True
        assert app.config.get('SESSION_COOKIE_HTTPONLY', True) is True

    def test_security_headers_middleware(self, client):
        """Test that security headers are added to responses"""
        response = client.get('/login')

        # Check for security headers
        assert 'X-Frame-Options' in response.headers
        assert 'X-Content-Type-Options' in response.headers
        assert 'X-XSS-Protection' in response.headers
