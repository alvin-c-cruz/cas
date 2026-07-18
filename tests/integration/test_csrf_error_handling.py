"""Integration test for graceful CSRF-error handling (BUG-PA-SESSION-UNEXPECTED-LOGOUT).

CSRF is disabled by default in the testing config so it does not get in the way of
the rest of the suite (see config.py TestingConfig.WTF_CSRF_ENABLED = False and the
identical pattern in tests/integration/test_login_rate_limit.py). This test builds a
FRESH app with CSRF enabled at init time, matching that same pattern, rather than
mutating the shared session app.
"""
import os

import pytest

from app import create_app, db

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def csrf_client(monkeypatch):
    """A dedicated app + client with CSRF protection enabled at init time."""
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    import config as config_module  # import here: config.py validates SECRET_KEY at import
    monkeypatch.setattr(config_module.TestingConfig, 'WTF_CSRF_ENABLED', True)
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        try:
            yield app.test_client()
        finally:
            db.session.remove()
            db.drop_all()


def test_stale_session_csrf_error_redirects_to_login_gracefully(csrf_client):
    """Reproduces the production incident: a POST carrying a CSRF token value but
    whose SESSION has no 'csrf_token' key at all (the exact 'CSRF session token is
    missing' case -- distinct from a missing/expired/mismatched token) must redirect
    to /login with a friendly flash, not crash with an unhandled 500."""
    response = csrf_client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
        'csrf_token': 'stale-token-from-a-long-idle-page',
    }, follow_redirects=True)

    assert response.status_code == 200  # followed the redirect, not a 500
    assert b'session has expired' in response.data.lower()
    assert response.request.path == '/login'
