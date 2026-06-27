import pytest
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_admin_can_grant_viewer_a_module(client, db_session, admin_user, viewer_user, main_branch):
    _login(client, 'admin', 'admin123')
    # viewer_user starts with default_all_permissions(); set a single explicit module
    resp = client.post(f'/users/{viewer_user.id}/edit', data={
        'username': 'viewer', 'email': 'viewer@test.com', 'full_name': 'Viewer User',
        'role': 'viewer', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
        'book_general_ledger': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db_session.get(User, viewer_user.id)
    perms = refreshed.get_book_permissions()
    assert perms.get('general_ledger') is True
    assert perms.get('accounts_payable') is False   # unchecked → False


def test_viewer_permission_grid_is_rendered(client, db_session, admin_user, viewer_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/users/{viewer_user.id}/edit')
    assert b'Book Access Permissions' in resp.data


def test_js_shows_grid_for_viewer(client, db_session, admin_user, viewer_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/users/{viewer_user.id}/edit')
    assert b"role === 'viewer'" in resp.data
