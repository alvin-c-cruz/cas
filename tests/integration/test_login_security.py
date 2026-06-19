"""
Security regression tests for the /login flow.

Covers three attacker-surface findings logged 2026-06-19 via /analyze-page:
  * BUG-SEC-04 — username enumeration via differential failure messages
  * BUG-SEC-05 — username lookup is case-sensitive (Admin != admin)
  * BUG-SEC-06 — password hash skipped for unknown user (timing enumeration)
"""
import pytest

pytestmark = [pytest.mark.users, pytest.mark.integration,
              pytest.mark.auth, pytest.mark.security]


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestLoginEnumeration:
    """BUG-SEC-04 — failure responses must not distinguish real vs fake users."""

    def test_wrong_password_and_unknown_user_return_identical_message(
            self, client, admin_user, main_branch):
        """A wrong password (real user) and an unknown username must produce the
        exact same flash message, so the response cannot confirm a username."""
        real = client.post('/login', data={
            'username': 'admin', 'password': 'definitely-wrong'
        }, follow_redirects=True)
        fake = client.post('/login', data={
            'username': 'nobody-here', 'password': 'definitely-wrong'
        }, follow_redirects=True)

        assert real.status_code == 401
        assert fake.status_code == 401
        assert b'Invalid username or password.' in real.data
        assert b'Invalid username or password.' in fake.data
        # The remaining-attempts hint is the enumeration leak — it must be gone.
        assert b'attempts remaining' not in real.data
        assert b'attempts remaining' not in fake.data

    def test_no_remaining_attempts_warning_after_repeated_failures(
            self, client, admin_user, main_branch):
        """Even close to lockout, the response must not leak how many attempts
        remain (which only ever appeared for existing users)."""
        last = None
        for _ in range(4):
            last = client.post('/login', data={
                'username': 'admin', 'password': 'definitely-wrong'
            }, follow_redirects=True)
        assert last is not None
        assert b'attempts remaining' not in last.data


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestUsernameCaseInsensitive:
    """BUG-SEC-05 — username lookup must be case-insensitive."""

    def test_login_succeeds_with_uppercased_username(
            self, client, admin_user, main_branch):
        """User stored as 'admin' must authenticate when entered as 'ADMIN'."""
        resp = client.post('/login', data={
            'username': 'ADMIN', 'password': 'admin123'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data or b'dashboard' in resp.data

    def test_failed_attempts_tracked_regardless_of_case(
            self, client, db_session, admin_user, main_branch):
        """Failed attempts on 'admin' and 'ADMIN' must accrue on the same row,
        so case variants cannot reset the lockout counter."""
        client.post('/login', data={
            'username': 'admin', 'password': 'definitely-wrong'
        }, follow_redirects=True)
        client.post('/login', data={
            'username': 'ADMIN', 'password': 'definitely-wrong'
        }, follow_redirects=True)
        db_session.refresh(admin_user)
        assert admin_user.failed_login_attempts == 2


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestLoginTimingEqualization:
    """BUG-SEC-06 — a password hash must be computed even for unknown users."""

    def test_password_hash_computed_for_unknown_user(self, client, monkeypatch):
        """The unknown-user path must still invoke check_password_hash so its
        response timing matches the wrong-password path."""
        import app.users.views as views

        calls = {'n': 0}
        real_fn = views.check_password_hash

        def spy(pwhash, password):
            calls['n'] += 1
            return real_fn(pwhash, password)

        monkeypatch.setattr(views, 'check_password_hash', spy)

        client.post('/login', data={
            'username': 'no-such-user', 'password': 'whatever'
        }, follow_redirects=True)

        assert calls['n'] >= 1, 'check_password_hash not called for unknown user'
