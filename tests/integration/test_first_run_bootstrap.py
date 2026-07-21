import pytest

from app import db
from app.users.models import User
from app.branches.models import Branch
from app.audit.models import AuditLog
from app.accounts.models import Account

pytestmark = [pytest.mark.integration, pytest.mark.users]

NONWHITELISTED = 'founder@example.com'
PW = 'LongPassword123!'


def _register(client, username, email=NONWHITELISTED):
    return client.post('/register', data={
        'username': username, 'email': email, 'full_name': 'Founder',
        'password': PW, 'confirm_password': PW,
    }, follow_redirects=False)


def _add_admin(db_session, username='root'):
    u = User(username=username, email=f'{username}@t.com', full_name='Root',
             role='admin', is_active=True)
    u.set_password(PW)
    db_session.add(u)
    db_session.commit()
    return u


def test_first_run_admin_username_creates_active_admin_and_branch(client, db_session):
    resp = _register(client, 'admin')
    assert resp.status_code in (301, 302)  # redirect to dashboard (auto-login) on success

    admin = User.query.filter_by(username='admin').first()
    assert admin is not None
    assert admin.role == 'admin'
    assert admin.is_active is True

    branch = Branch.query.filter_by(code='MAIN').first()
    assert branch is not None and branch.name == 'Main Office'
    assert branch.id in {b.id for b in admin.branches.all()}

    assert AuditLog.query.filter_by(action='first_run_admin_bootstrap',
                                    record_id=admin.id).first() is not None


def test_first_run_unblocks_the_app_end_to_end(client, db_session):
    """After bootstrap the admin is auto-logged-in and reaches the dashboard
    with the branch auto-selected."""
    _register(client, 'admin')
    branch = Branch.query.filter_by(code='MAIN').first()

    client.post('/login', data={'username': 'admin', 'password': PW}, follow_redirects=True)
    resp = client.get('/dashboard', follow_redirects=True)
    assert resp.status_code == 200
    assert b'No branches available' not in resp.data
    with client.session_transaction() as sess:
        assert sess.get('selected_branch_id') == branch.id


def test_first_run_bootstrap_auto_logs_in(client, db_session):
    """Bootstrap now auto-logs-in the admin: no separate /login needed, lands on dashboard."""
    resp = _register(client, 'admin')                       # follow_redirects=False
    assert resp.status_code in (301, 302)
    assert '/login' not in resp.headers['Location']          # NOT bounced to login
    assert '/dashboard' in resp.headers['Location'] or resp.headers['Location'].endswith('/')

    # Reachable immediately WITHOUT a separate login POST:
    page = client.get('/dashboard', follow_redirects=True)
    assert page.status_code == 200
    assert b'No branches available' not in page.data

    admin = User.query.filter_by(username='admin').first()
    assert AuditLog.query.filter_by(action='login_success', record_id=admin.id).first() is not None

    branch = Branch.query.filter_by(code='MAIN').first()
    with client.session_transaction() as sess:
        assert sess.get('selected_branch_id') == branch.id


def test_first_run_bootstrap_sets_last_login(client, db_session):
    """BUG-FIRSTRUN-BOOTSTRAP-NO-LAST-LOGIN: the bootstrap auto-login must set
    last_login like a normal /login does, so User Management doesn't show
    'Never' for an admin who is actively logged in."""
    _register(client, 'admin')
    admin = User.query.filter_by(username='admin').first()
    assert admin.last_login is not None


def test_non_admin_username_on_empty_db_creates_nothing(client, db_session):
    resp = _register(client, 'owner')
    assert resp.status_code == 200  # re-renders the form with the whitelist error
    assert User.query.count() == 0
    assert Branch.query.count() == 0


def test_bypass_closed_when_admin_exists(client, db_session):
    _add_admin(db_session, username='root')
    resp = _register(client, 'admin')  # non-whitelisted email, admin exists
    assert resp.status_code == 200     # whitelist error re-renders the form
    assert User.query.filter_by(username='admin').first() is None
    # no second admin, no extra branch
    assert User.query.filter_by(role='admin').count() == 1
    assert Branch.query.count() == 0


def test_race_admin_appears_between_form_and_view_is_refused(client, db_session, monkeypatch):
    """Form validates as first-run (no admin), but an admin appears before the
    view's check -> refused, no admin/branch created."""
    calls = {'n': 0}

    def fake_has_admin():
        calls['n'] += 1
        return calls['n'] > 1  # False for the form's check, True for the view's

    monkeypatch.setattr('app.users.utils.system_has_admin', fake_has_admin)
    resp = _register(client, 'admin')
    assert resp.status_code in (301, 302)  # redirected back to register
    assert User.query.filter_by(username='admin').first() is None
    assert Branch.query.count() == 0


FORBIDDEN_HINTS = [
    b'no administrator exists',
    b'initial system administrator',
    b'first-run',
    b'first run',
    b'bootstrap',
]


def test_register_page_shows_no_bootstrap_indication(client, db_session):
    # Empty DB (first-run active under the hood)
    empty_body = client.get('/register').data.lower()
    for hint in FORBIDDEN_HINTS:
        assert hint not in empty_body, f'register page leaked bootstrap hint: {hint!r}'

    # With an admin present (first-run closed)
    _add_admin(db_session, username='root')
    admin_body = client.get('/register').data.lower()
    for hint in FORBIDDEN_HINTS:
        assert hint not in admin_body, f'register page leaked bootstrap hint: {hint!r}'


def test_first_run_bootstrap_seeds_standard_parent_accounts(client, db_session):
    _register(client, 'admin')
    assert Account.query.count() == 27
    cash = Account.query.filter_by(code='111000').first()
    assert cash is not None
    assert cash.parent_id is None

    assert AuditLog.query.filter_by(module='account', action='seed').first() is not None


def test_non_admin_username_on_empty_db_does_not_seed_accounts(client, db_session):
    _register(client, 'owner')
    assert Account.query.count() == 0
