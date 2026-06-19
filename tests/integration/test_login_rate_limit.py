"""Integration tests for per-IP login rate limiting (BUG-SEC-01).

Account lockout (per-account) already exists; these cover the IP-based throttle
that stops credential-stuffing across many usernames from one source and
lockout-as-DoS.

Rate limiting is DISABLED by default in the testing config so it does not
throttle the rest of the suite. Flask-Limiter only creates its storage (and only
enforces) when RATELIMIT_ENABLED is true at init_app time, and Flask forbids
re-registering before_request after the first request — so these tests build a
FRESH app with the flag patched on rather than mutating the shared session app,
and restore the disabled state afterwards.
"""
import os

import pytest

from app import create_app, db, limiter

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def rl_client(monkeypatch):
    """A dedicated app + client with rate limiting enabled at init time."""
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    import config as config_module  # import here: config.py validates SECRET_KEY at import
    monkeypatch.setattr(config_module.TestingConfig, 'RATELIMIT_ENABLED', True)
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        limiter.enabled = True
        limiter.reset()
        try:
            yield app.test_client()
        finally:
            limiter.reset()
            limiter.enabled = False   # protect the rest of the suite (shared singleton)
            db.session.remove()
            db.drop_all()


def test_login_rate_limited_after_threshold(rl_client):
    """After the per-IP threshold, /login POSTs return 429 instead of 401."""
    codes = [rl_client.post('/login', data={'username': 'nosuchuser', 'password': 'wrongpass'}).status_code
             for _ in range(13)]
    assert codes[0] != 429, f"First attempt must not be rate-limited, got {codes}"
    assert 429 in codes, f"Expected a 429 once the per-IP threshold is crossed, got {codes}"


def test_register_rate_limited_after_threshold(rl_client):
    """The same IP throttle protects /register."""
    codes = [rl_client.post('/register', data={
        'username': f'u{i}', 'email': f'u{i}@x.com',
        'password': 'x', 'confirm_password': 'x',
    }).status_code for i in range(13)]
    assert 429 in codes, f"Expected a 429 on /register once the threshold is crossed, got {codes}"


def test_login_not_limited_when_disabled(client, db_session):
    """With rate limiting disabled (the testing default), many POSTs never 429.

    Guards the rest of the suite: tests that log in repeatedly must not trip the
    limiter just because it exists.
    """
    codes = [client.post('/login', data={'username': 'nosuchuser', 'password': 'wrongpass'}).status_code
             for _ in range(15)]
    assert 429 not in codes, f"Disabled limiter must not throttle, got {codes}"
