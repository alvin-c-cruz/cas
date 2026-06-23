"""Users are onboarded via self-registration, not admin-created.

The admin "Create User" capability has been removed:
- the `/users/create` route no longer exists (404), and
- the User Management list page shows no "Create User" button.

Admins still promote/adjust roles and branches via the edit route.
"""
import pytest
from app.users.models import User

pytestmark = [pytest.mark.users, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestCreateUserRemoved:
    def test_create_route_get_is_404(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/users/create')
        assert resp.status_code == 404

    def test_create_route_post_is_404_and_creates_nothing(self, client, db_session,
                                                          admin_user, main_branch):
        login(client)
        before = User.query.count()
        resp = client.post('/users/create', data={
            'username': 'shouldnotexist',
            'email': 'shouldnotexist@example.com',
            'full_name': 'Should Not Exist',
            'role': 'staff',
            'password': 'DemoPass#2026',
            'confirm_password': 'DemoPass#2026',
            'is_active': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 404
        assert User.query.filter_by(username='shouldnotexist').first() is None
        assert User.query.count() == before

    def test_list_page_has_no_create_button(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/users')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Create User' not in html
        assert '/users/create' not in html
