import pytest

from app.users.models import User
from app.users.utils import system_has_admin, FIRST_RUN_ADMIN_USERNAME

pytestmark = [pytest.mark.unit, pytest.mark.users]


def _add_user(db_session, username, role, is_active):
    u = User(username=username, email=f'{username}@t.com', full_name=username.title(),
             role=role, is_active=is_active)
    u.set_password('LongPassword123!')
    db_session.add(u)
    db_session.commit()
    return u


def test_no_users_means_no_admin(db_session):
    assert system_has_admin() is False


def test_active_admin_present(db_session):
    _add_user(db_session, 'root', 'admin', True)
    assert system_has_admin() is True


def test_inactive_admin_does_not_count(db_session):
    _add_user(db_session, 'root', 'admin', False)
    assert system_has_admin() is False


def test_non_admin_active_user_does_not_count(db_session):
    _add_user(db_session, 'clerk', 'staff', True)
    assert system_has_admin() is False


def test_reserved_username_constant_is_exact_lowercase_admin():
    assert FIRST_RUN_ADMIN_USERNAME == 'admin'
