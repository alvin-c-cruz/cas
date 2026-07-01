from app.utils.admin_approval import sole_full_access_user_can_auto_approve, another_active_reviewer_exists
from app.users.models import User


def _login(client, username, password='pw12345'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def test_sole_full_access_user_auto_approves(app, db_session, admin_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_full_access_user_can_auto_approve() is True


def test_two_full_access_users_do_not_auto_approve(app, db_session, admin_user):
    second = User(username='admin2', email='a2@x.com', full_name='Admin Two', role='admin', is_active=True)
    second.set_password('pw12345')
    db_session.add(second)
    db_session.commit()
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_full_access_user_can_auto_approve() is False


def test_accountant_never_auto_approves(app, db_session, accountant_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(accountant_user)
        assert sole_full_access_user_can_auto_approve() is False


# --- another_active_reviewer_exists ---

def test_another_active_reviewer_exists_with_two_admins(app, db_session, admin_user):
    second = User(username='admin2', email='a2@x.com', full_name='Admin Two',
                  role='admin', is_active=True)
    second.set_password('pw12345')
    db_session.add(second)
    db_session.commit()
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert another_active_reviewer_exists() is True


def test_another_active_reviewer_not_exists_sole_admin(app, db_session, admin_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert another_active_reviewer_exists() is False
