import pytest

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_accountant_blocked_from_users_list(client, db_session, admin_user, accountant_user, main_branch):
    _login(client, 'accountant', 'accountant123')
    resp = client.get('/users', follow_redirects=True)
    assert b'administrator privileges' in resp.data.lower() or b'do not have' in resp.data.lower()


def test_accountant_blocked_from_edit_user(client, db_session, admin_user, accountant_user, staff_user, main_branch):
    _login(client, 'accountant', 'accountant123')
    resp = client.get(f'/users/{staff_user.id}/edit', follow_redirects=True)
    # redirected to dashboard, not the edit form
    assert b'Access Permissions' not in resp.data


def test_admin_still_reaches_users(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get('/users')
    assert resp.status_code == 200
