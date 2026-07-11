import pytest
from werkzeug.datastructures import MultiDict

from app.users.models import User
from app.users.forms import RegistrationForm

pytestmark = [pytest.mark.unit, pytest.mark.users]

NONWHITELISTED = 'anyone@example.com'


def _formdata(username, email=NONWHITELISTED):
    return MultiDict({
        'username': username,
        'email': email,
        'full_name': 'Test User',
        'password': 'LongPassword123!',
        'confirm_password': 'LongPassword123!',
    })


def _email_rejected(form):
    return any('not pre-approved' in e for e in form.errors.get('email', []))


def _add_admin(db_session, username='root'):
    u = User(username=username, email=f'{username}@t.com', full_name='Root',
             role='admin', is_active=True)
    u.set_password('LongPassword123!')
    db_session.add(u)
    db_session.commit()
    return u


def test_firstrun_admin_username_bypasses_whitelist(app, db_session):
    """Empty DB + username 'admin' + non-whitelisted email -> form validates."""
    with app.test_request_context():
        form = RegistrationForm(formdata=_formdata('admin'))
        assert form.validate(), form.errors
        assert not _email_rejected(form)


def test_firstrun_non_admin_username_enforces_whitelist(app, db_session):
    """Empty DB + username 'owner' -> whitelist still enforced (email rejected)."""
    with app.test_request_context():
        form = RegistrationForm(formdata=_formdata('owner'))
        assert not form.validate()
        assert _email_rejected(form)


def test_firstrun_caps_admin_enforces_whitelist(app, db_session):
    """Case-sensitive: 'Admin' does NOT qualify -> whitelist enforced."""
    with app.test_request_context():
        form = RegistrationForm(formdata=_formdata('Admin'))
        assert not form.validate()
        assert _email_rejected(form)


def test_bypass_closed_once_admin_exists(app, db_session):
    """With an admin present, even username 'admin' hits the whitelist."""
    _add_admin(db_session, username='root')  # 'admin' username still free
    with app.test_request_context():
        form = RegistrationForm(formdata=_formdata('admin'))
        assert not form.validate()
        assert _email_rejected(form)
