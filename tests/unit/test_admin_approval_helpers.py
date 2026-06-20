from app.utils.admin_approval import sole_admin_can_auto_approve
from app.users.models import User


def _login(client, username, password='pw12345'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def test_sole_admin_auto_approves(app, db_session, admin_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_admin_can_auto_approve() is True


def test_two_admins_do_not_auto_approve(app, db_session, admin_user):
    second = User(username='admin2', email='a2@x.com', full_name='Admin Two', role='admin', is_active=True)
    second.set_password('pw12345')
    db_session.add(second)
    db_session.commit()
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_admin_can_auto_approve() is False


def test_accountant_never_auto_approves(app, db_session, accountant_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(accountant_user)
        assert sole_admin_can_auto_approve() is False
