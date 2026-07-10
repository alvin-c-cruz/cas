"""Forced change of the seeded default admin password (config-gated).

Every seed path historically minted `admin/admin123`, and all four live instances
were first-run seeded that way. This guard forces ANY user still on `admin123` to
change it before reaching any other page.

Config-gated, mirroring the rate-limit + TestingErrorsConfig pattern: the flag is
ON in production/development, OFF in the plain testing config (so the suite's
admin123 fixtures are not force-redirected), and flipped ON here with a fresh app.
Because a properly-configured admin never has admin123, the guard is dormant during
the rest of the suite anyway -- it only fires where it is deliberately exercised,
which is exactly here.
"""
import pytest

from app import create_app, db
from app.branches.models import Branch
from app.users.models import User
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.auth]

STRONG = 'Str0ng#Rotated-2026'


@pytest.fixture
def guard(monkeypatch):
    """A fresh testing app with the guard flag ON, one branch, and a user factory."""
    import os
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    import config as config_module
    monkeypatch.setattr(config_module.TestingConfig, 'ENFORCE_DEFAULT_PW_CHANGE', True)
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        branch = Branch(name='Main', code='MAIN')
        db.session.add(branch)
        db.session.commit()

        def make_user(username='admin', password='admin123', role='admin'):
            from app.users.module_access import default_all_permissions
            u = User(username=username, email=f'{username}@t.com', full_name=username,
                     role=role, is_active=True)
            u.set_password(password)
            if role != 'admin':
                u.set_book_permissions(default_all_permissions())
            db.session.add(u)
            db.session.flush()
            if role != 'admin':
                u.set_branches([branch])
            db.session.commit()
            return u

        with app.test_client() as client:
            yield client, app, make_user
        db.session.remove()
        db.drop_all()


def _login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)


def _change_pw_url():
    return '/profile/change-password'


def test_default_admin_forced_to_change_password_at_login(guard):
    client, app, make_user = guard
    make_user('admin', 'admin123')
    resp = _login(client, 'admin', 'admin123')
    assert resp.status_code == 302
    assert _change_pw_url() in resp.headers['Location']


def test_default_admin_cannot_reach_other_pages(guard):
    client, app, make_user = guard
    make_user('admin', 'admin123')
    _login(client, 'admin', 'admin123')
    # Every non-exempt page bounces back to change-password.
    resp = client.get('/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert _change_pw_url() in resp.headers['Location']


def test_default_admin_can_reach_change_password_and_logout(guard):
    client, app, make_user = guard
    make_user('admin', 'admin123')
    _login(client, 'admin', 'admin123')
    assert client.get(_change_pw_url()).status_code == 200
    assert client.get('/logout', follow_redirects=False).status_code == 302


def test_changing_password_lifts_the_gate(guard):
    client, app, make_user = guard
    make_user('admin', 'admin123')
    _login(client, 'admin', 'admin123')
    resp = client.post(_change_pw_url(), data={
        'current_password': 'admin123',
        'new_password': STRONG,
        'confirm_password': STRONG,
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert _change_pw_url() not in resp.headers['Location']   # freed
    assert client.get('/dashboard', follow_redirects=False).status_code == 200


def test_non_default_admin_unaffected(guard):
    client, app, make_user = guard
    make_user('admin', STRONG)
    resp = _login(client, 'admin', STRONG)
    assert resp.status_code == 302
    assert _change_pw_url() not in resp.headers['Location']
    assert client.get('/dashboard', follow_redirects=False).status_code == 200


def test_non_admin_with_default_password_also_forced(guard):
    """The trigger is the password admin123, not the admin role -- any account that
    holds it got it from a seed or a shell, never a user-chosen password (the
    validator blocklists it)."""
    client, app, make_user = guard
    make_user('acct', 'admin123', role='accountant')
    _login(client, 'acct', 'admin123')
    resp = client.get('/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert _change_pw_url() in resp.headers['Location']


def test_pre_existing_session_is_caught(guard):
    """A session alive from before the guard deployed (SECRET_KEY is stable) never
    went through the login-time check -- the before_request hook must still catch it."""
    client, app, make_user = guard
    u = make_user('admin', 'admin123')
    # Forge an authenticated session WITHOUT going through login().
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id)
        s['_fresh'] = True
    resp = client.get('/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert _change_pw_url() in resp.headers['Location']


def test_console_rotation_self_heals(guard):
    """If the admin is rotated via a PA console while a session is flagged, the next
    request must re-verify and release the gate -- not trust a cached 'default'."""
    client, app, make_user = guard
    u = make_user('admin', 'admin123')
    _login(client, 'admin', 'admin123')
    assert _change_pw_url() in client.get('/dashboard').headers.get('Location', '')

    # Simulate a console-side rotation. The test body runs inside the fixture's app
    # context, so this is the same session the request handlers use.
    u.set_password(STRONG)
    db.session.commit()

    assert client.get('/dashboard', follow_redirects=False).status_code == 200


def test_guard_off_in_plain_testing_config():
    """Proof the 185-file sweep is unnecessary: with the flag OFF (the default
    testing config), an admin123 admin reaches the dashboard untouched.

    Deliberately does NOT take the `guard` fixture -- its monkeypatch would flip the
    flag on for this app too.
    """
    import os
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-testing-only')
    app = create_app('testing')  # ENFORCE_DEFAULT_PW_CHANGE is False here
    with app.app_context():
        db.create_all()
        br = Branch(name='Main', code='MAIN')
        db.session.add(br)
        u = User(username='admin', email='a@t.com', full_name='A', role='admin', is_active=True)
        u.set_password('admin123')
        db.session.add(u)
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'username': 'admin', 'password': 'admin123'})
            assert c.get('/dashboard', follow_redirects=False).status_code == 200
        db.session.remove()
        db.drop_all()


def test_forced_login_and_change_are_audited(guard):
    client, app, make_user = guard
    make_user('admin', 'admin123')
    _login(client, 'admin', 'admin123')
    client.post(_change_pw_url(), data={
        'current_password': 'admin123',
        'new_password': STRONG,
        'confirm_password': STRONG,
    }, follow_redirects=False)
    with app.app_context():
        assert AuditLog.query.filter_by(module='users', action='change_password').first() is not None
