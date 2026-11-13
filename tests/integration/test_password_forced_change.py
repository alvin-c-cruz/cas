"""A password someone else set must be changed at the next login, and a sole admin can be let back in.

Work orders 2026-11-10-force-password-change-after-admin-reset (a) and 2026-11-10-cli-admin-password-reset (b),
from Alvin's "what happens if a user forgot the password" (10 Nov 2026; "Both"). Owner, 12 Nov 2026, PW-3:
"A" -- any password an admin sets for someone else is forced to change, a new user's first one included.
(CAS has no admin path that sets a new user's first password: new users choose their own at /register.)

(a) `users.must_change_password`: set when an admin sets another user's password, and by the CLI reset;
    while it is set every page redirects to Change password (the change-password, logout, login and
    static endpoints excepted), whatever the session cached; the user's own change clears it. An
    admin's change of their OWN password does not set it. Both events are audited.
(b) `flask reset-password <username>`: the new password is prompted twice, hidden, never an argument;
    the change-password form's rules apply; the lockout is cleared; the flag is set; an audit row
    `password_reset` notes "password_reset via CLI"; an unknown or inactive user exits non-zero.
"""
import pytest

from app import db
from app.audit.models import AuditLog
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.users]

NEW = 'Brand-New#Pass2026'
OWN = 'Chosen-By-Me#2026x'


def _login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _edit_payload(main_branch, **overrides):
    data = {'username': 'staff', 'email': 'staff@test.com', 'full_name': 'Staff User',
            'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y'}
    data.update(overrides)
    return data


def _admin_resets_staff(client, staff_user, main_branch):
    _login(client, 'admin', 'admin123')
    client.post(f'/users/{staff_user.id}/edit',
                data=_edit_payload(main_branch, password=NEW, confirm_password=NEW), follow_redirects=True)
    client.get('/logout', follow_redirects=True)


# ------------------------------------------------------------------ (a)
class TestForcedChange:

    def test_an_admin_reset_flags_the_user_and_is_audited(self, client, db_session, admin_user, staff_user, main_branch):
        _admin_resets_staff(client, staff_user, main_branch)
        db_session.refresh(staff_user)
        assert staff_user.check_password(NEW), 'anti-vacuity: the reset did not happen'
        assert staff_user.must_change_password is True
        assert AuditLog.query.filter_by(module='user', action='password_reset', record_id=staff_user.id).count() == 1

    def test_the_next_login_goes_straight_to_change_password(self, client, db_session, admin_user, staff_user, main_branch):
        _admin_resets_staff(client, staff_user, main_branch)
        _login(client, 'staff', NEW)
        resp = client.get('/dashboard')
        assert resp.status_code == 302 and '/profile/change-password' in resp.headers['Location']
        page = client.get('/profile/change-password')
        assert page.status_code == 200

    def test_a_session_cache_cannot_skip_it(self, client, db_session, admin_user, staff_user, main_branch):
        _admin_resets_staff(client, staff_user, main_branch)
        _login(client, 'staff', NEW)
        with client.session_transaction() as s:
            s['pw_is_default'] = False                     # the default-password fast path
        resp = client.get('/dashboard')
        assert resp.status_code == 302 and '/profile/change-password' in resp.headers['Location']

    def test_logout_stays_reachable(self, client, db_session, admin_user, staff_user, main_branch):
        _admin_resets_staff(client, staff_user, main_branch)
        _login(client, 'staff', NEW)
        resp = client.get('/logout')
        assert '/profile/change-password' not in resp.headers.get('Location', '')

    def test_the_users_own_change_clears_it_and_is_audited(self, client, db_session, admin_user, staff_user, main_branch):
        _admin_resets_staff(client, staff_user, main_branch)
        _login(client, 'staff', NEW)
        client.post('/profile/change-password', data={'current_password': NEW, 'new_password': OWN,
                                                      'confirm_password': OWN}, follow_redirects=True)
        db_session.refresh(staff_user)
        assert staff_user.check_password(OWN)
        assert staff_user.must_change_password is False
        row = (AuditLog.query.filter_by(module='users', action='change_password', record_id=staff_user.id)
               .order_by(AuditLog.id.desc()).first())
        assert row is not None and 'forced' in (row.notes or '').lower()
        assert client.get('/dashboard').status_code != 302 or \
            '/profile/change-password' not in client.get('/dashboard').headers.get('Location', '')

    def test_an_admins_change_of_their_own_password_is_not_flagged(self, client, db_session, admin_user, main_branch):
        admin_user.set_branches([main_branch]) if hasattr(admin_user, 'set_branches') else None
        db_session.commit()
        _login(client, 'admin', 'admin123')
        client.post(f'/users/{admin_user.id}/edit', data={
            'username': 'admin', 'email': 'admin@test.com', 'full_name': 'Admin User', 'role': 'admin',
            'branch_ids': [str(main_branch.id)], 'is_active': 'y', 'password': NEW, 'confirm_password': NEW},
            follow_redirects=True)
        db_session.refresh(admin_user)
        assert admin_user.check_password(NEW), 'anti-vacuity: the own change did not happen'
        assert admin_user.must_change_password is False

    def test_a_new_user_starts_unflagged(self, db_session):
        u = User(username='fresh', email='fresh@test.com', full_name='Fresh', role='staff', is_active=True)
        u.set_password(OWN)
        db_session.add(u); db_session.commit()
        assert u.must_change_password is False


# ------------------------------------------------------------------ (b)
class TestCliReset:

    @pytest.fixture
    def runner(self, app):
        return app.test_cli_runner()

    def test_it_resets_clears_the_lockout_flags_and_audits(self, runner, db_session, staff_user):
        from datetime import timedelta
        from app.utils import ph_now
        staff_user.failed_login_attempts = 5
        staff_user.account_locked_until = ph_now() + timedelta(minutes=10)
        db_session.commit()
        result = runner.invoke(args=['reset-password', 'staff'], input=f'{NEW}\n{NEW}\n')
        assert result.exit_code == 0, result.output
        assert NEW not in result.output                      # hidden input, never echoed
        db_session.refresh(staff_user)
        assert staff_user.check_password(NEW)
        assert staff_user.failed_login_attempts == 0 and staff_user.account_locked_until is None
        assert staff_user.must_change_password is True
        row = AuditLog.query.filter_by(module='user', action='password_reset', record_id=staff_user.id).one()
        assert 'password_reset via CLI' in (row.notes or '')

    def test_a_mismatch_changes_nothing(self, runner, db_session, staff_user):
        result = runner.invoke(args=['reset-password', 'staff'], input=f'{NEW}\nSomething-Else#99x\n')
        assert result.exit_code != 0
        db_session.refresh(staff_user)
        assert not staff_user.check_password(NEW)

    def test_a_weak_password_is_refused(self, runner, db_session, staff_user):
        result = runner.invoke(args=['reset-password', 'staff'], input='short\nshort\n')
        assert result.exit_code != 0
        db_session.refresh(staff_user)
        assert not staff_user.check_password('short')
        assert staff_user.must_change_password is False

    def test_an_unknown_user_exits_non_zero(self, runner, db_session):
        result = runner.invoke(args=['reset-password', 'nobody'], input=f'{NEW}\n{NEW}\n')
        assert result.exit_code != 0 and 'nobody' in result.output

    def test_an_inactive_user_is_refused(self, runner, db_session, staff_user):
        staff_user.is_active = False
        db_session.commit()
        result = runner.invoke(args=['reset-password', 'staff'], input=f'{NEW}\n{NEW}\n')
        assert result.exit_code != 0
        db_session.refresh(staff_user)
        assert not staff_user.check_password(NEW)

    def test_the_password_is_never_an_argument(self, runner, db_session, staff_user):
        result = runner.invoke(args=['reset-password', 'staff', NEW], input=f'{NEW}\n{NEW}\n')
        assert result.exit_code != 0                         # no second positional argument


def test_the_migration_starts_every_user_unflagged_and_downgrades_cleanly(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / 'pwforce.db'; db_path.touch()
    env = dict(os.environ, SECRET_KEY='migration-test', FLASK_APP='flask_app.py',
               SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}')
    env.pop('CAS_EXPECT_COMPANY', None)
    run = lambda *a: subprocess.run([sys.executable, '-m', 'flask', 'db', *a], cwd=root, env=env,
                                    capture_output=True, text=True, check=True)
    run('upgrade', 'chqpay_0001')
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO users (username, email, full_name, password_hash, role, is_active, "
                "failed_login_attempts) VALUES ('old', 'old@x.com', 'Old', 'x', 'staff', 1, 0)")
    con.commit(); con.close()
    run('upgrade', 'pwforce_0001')
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT must_change_password FROM users").fetchall() == [(0,)]
    con.close()
    heads = run('heads').stdout
    assert heads.count('(head)') == 1 and 'pwforce_0001' in heads
    run('downgrade', 'chqpay_0001')
    con = sqlite3.connect(db_path)
    assert 'must_change_password' not in {r[1] for r in con.execute("PRAGMA table_info(users)")}
    con.close()
