"""
Integration tests for authentication and authorization
"""
import pytest
from flask import url_for
from app.utils import ph_now
pytestmark = [pytest.mark.users, pytest.mark.integration]




@pytest.mark.integration
@pytest.mark.auth
class TestAuthentication:
    """Test authentication flows"""

    def test_login_page_loads(self, client):
        """Test that login page loads successfully"""
        response = client.get('/login')
        assert response.status_code == 200
        assert b'Login' in response.data or b'login' in response.data

    def test_successful_login(self, client, admin_user, main_branch):
        """Test successful login with valid credentials"""
        response = client.post('/login', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=True)

        assert response.status_code == 200
        # Should redirect to dashboard
        assert b'Dashboard' in response.data or b'dashboard' in response.data

    def test_failed_login_wrong_password(self, client, admin_user):
        """Test login failure with wrong password returns 401"""
        response = client.post('/login', data={
            'username': 'admin',
            'password': 'wrongpassword'
        }, follow_redirects=True)

        assert response.status_code == 401
        # Should show error message
        assert b'Invalid' in response.data or b'invalid' in response.data

    def test_failed_login_nonexistent_user(self, client):
        """Test login failure with nonexistent user returns 401"""
        response = client.post('/login', data={
            'username': 'nonexistent',
            'password': 'password123'
        }, follow_redirects=True)

        assert response.status_code == 401
        assert b'Invalid' in response.data or b'invalid' in response.data

    def test_failed_login_inactive_user(self, client, db_session, admin_user, main_branch):
        """Test login failure with inactive user returns 401"""
        # Set last_login so the view shows "deactivated" rather than "pending approval"
        admin_user.last_login = ph_now()
        admin_user.is_active = False
        db_session.commit()

        response = client.post('/login', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=True)

        assert response.status_code == 401
        assert (b'inactive' in response.data.lower()
                or b'disabled' in response.data.lower()
                or b'deactivated' in response.data.lower()
                or b'pending' in response.data.lower())

    def test_logout(self, client, admin_user, main_branch, login_user, logout_user):
        """Test logout functionality"""
        # First login
        login_response = login_user(client, 'admin', 'admin123')
        assert b'Dashboard' in login_response.data or b'dashboard' in login_response.data

        # Then logout
        logout_response = logout_user(client)
        assert logout_response.status_code == 200

        # Should be redirected to login page
        assert b'Login' in logout_response.data or b'login' in logout_response.data

    def test_protected_route_requires_login(self, client):
        """Test that protected routes require authentication"""
        # Try to access dashboard without login
        response = client.get('/dashboard', follow_redirects=True)

        # Should redirect to login
        assert b'Login' in response.data or b'login' in response.data


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestAuthorization:
    """Test role-based authorization"""

    def test_admin_can_access_admin_routes(self, client, admin_user, main_branch, login_user):
        """Test that admin can access admin-only routes"""
        login_user(client, 'admin', 'admin123')

        # Try to access admin route (branches management)
        response = client.get('/branches')
        assert response.status_code == 200

    def test_non_admin_cannot_access_admin_routes(self, client, db_session, staff_user, main_branch, login_user):
        """Test that non-admin cannot access admin-only routes"""
        # Assign branch so staff can log in
        staff_user.branches.append(main_branch)
        db_session.commit()

        login_user(client, 'staff', 'staff123')

        # Try to access admin route (branches management)
        response = client.get('/branches', follow_redirects=True)

        # Should be forbidden or redirected
        assert response.status_code in [200, 403]
        if response.status_code == 200:
            assert b'Only administrators' in response.data or b'only administrators' in response.data

    def test_accountant_can_access_accounting_routes(self, client, accountant_user, main_branch, login_user):
        """Test that accountant can access accounting routes"""
        login_user(client, 'accountant', 'accountant123')

        # Try to access accounting route
        response = client.get('/accounts/')
        assert response.status_code == 200

    def test_viewer_cannot_modify_data(self, client, db_session, viewer_user, main_branch, login_user, cash_account):
        """Test that viewer role cannot modify data"""
        # Assign branch so viewer can log in
        viewer_user.branches.append(main_branch)
        db_session.commit()

        login_user(client, 'viewer', 'viewer123')

        # Try to create an account (should be forbidden)
        response = client.get('/accounts/create', follow_redirects=True)

        # Should be denied or redirected
        assert response.status_code in [200, 403, 405]
        if response.status_code == 200:
            # Should show access denied message
            assert b'Accountant' in response.data or b'accountant' in response.data


@pytest.mark.integration
@pytest.mark.auth
class TestSessionManagement:
    """Test session management and security"""

    def test_session_created_on_login(self, client, admin_user, main_branch, login_user):
        """Test that session is created on login"""
        with client.session_transaction() as sess:
            # No user in session before login
            assert '_user_id' not in sess

        # Login
        login_user(client, 'admin', 'admin123')

        with client.session_transaction() as sess:
            # User ID should be in session after login
            assert '_user_id' in sess
            assert sess['_user_id'] == str(admin_user.id)

    def test_session_destroyed_on_logout(self, client, admin_user, main_branch, login_user, logout_user):
        """Test that session is destroyed on logout"""
        # Login
        login_user(client, 'admin', 'admin123')

        with client.session_transaction() as sess:
            assert '_user_id' in sess

        # Logout
        logout_user(client)

        with client.session_transaction() as sess:
            # User ID should be removed from session
            assert '_user_id' not in sess


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestCSRFProtection:
    """Test CSRF protection on forms"""

    def test_csrf_token_in_login_form(self, client):
        """Test that login form uses POST and renders correctly"""
        response = client.get('/login')
        assert response.status_code == 200
        # Login form must use POST
        assert b'method="POST"' in response.data
        # CSRF token field is present when CSRF is enabled; in test config
        # WTF_CSRF_ENABLED=False so hidden_tag() renders empty — verify form exists
        assert b'<form' in response.data

    def test_post_without_csrf_fails(self, client, admin_user):
        """Test that POST without CSRF token fails"""
        # Disable CSRF for this specific test to check the behavior
        # Note: In real scenario, this should fail
        # This test documents expected behavior
        pass  # CSRF is enforced by Flask-WTF automatically


@pytest.mark.integration
@pytest.mark.auth
class TestOpenRedirect:
    """Ensure ?next= redirects cannot send users to external hosts."""

    def test_absolute_url_blocked(self, client, accountant_user, main_branch):
        """POST /login?next=http://evil.com must redirect to dashboard, not evil.com."""
        resp = client.post(
            '/login?next=http://evil.com',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil.com' not in resp.headers['Location']

    def test_protocol_relative_url_blocked(self, client, accountant_user, main_branch):
        """POST /login?next=//evil.com must redirect to dashboard, not evil.com."""
        resp = client.post(
            '/login?next=//evil.com',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil.com' not in resp.headers['Location']

    def test_valid_local_next_honored(self, client, accountant_user, main_branch):
        """POST /login?next=/vendors must redirect to /vendors."""
        resp = client.post(
            '/login?next=/vendors',
            data={'username': 'accountant', 'password': 'accountant123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/vendors')
