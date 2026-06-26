"""Integration tests for Task 3: UserForm must require >=1 branch for non-admin roles."""
import pytest
from app.users.models import User
from app.branches.models import Branch

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login_admin(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _edit_user_post(client, user, branch_ids, role='accountant'):
    return client.post(
        f'/users/{user.id}/edit',
        data={
            'username': user.username,
            'email': user.email,
            'full_name': user.full_name,
            'role': role,
            'is_active': 'y',
            'branch_ids': branch_ids,
        },
        follow_redirects=False,
    )


class TestUserFormBranchRequired:

    def test_non_admin_with_no_branches_fails_validation(
        self, client, db_session, admin_user, main_branch
    ):
        """POSTing a non-admin role with no branch_ids re-renders with a validation error."""
        _login_admin(client)
        # Create a target user (needs at least 1 branch to be found in DB; starts with one)
        target = User(username='tgt1', email='tgt1@test.com',
                      full_name='Target One', role='accountant', is_active=True)
        target.set_password('Pass123!test')
        db_session.add(target)
        db_session.flush()
        target.branches.append(main_branch)
        db_session.commit()

        resp = _edit_user_post(client, target, branch_ids=[], role='accountant')

        assert resp.status_code == 200, "form re-renders (not redirected) on validation error"
        assert b'Assign at least one branch for non-admin roles.' in resp.data

        # User's branch must NOT have been wiped
        refreshed = db_session.get(User, target.id)
        assert main_branch.id in refreshed.get_branch_ids(), \
            "branch assignment must not be cleared on validation failure"

    def test_non_admin_with_one_branch_saves(
        self, client, db_session, admin_user, main_branch
    ):
        """POSTing a non-admin role with >=1 branch_id saves and redirects."""
        _login_admin(client)
        target = User(username='tgt2', email='tgt2@test.com',
                      full_name='Target Two', role='viewer', is_active=True)
        target.set_password('Pass123!test')
        db_session.add(target)
        db_session.flush()
        target.branches.append(main_branch)
        db_session.commit()

        resp = _edit_user_post(client, target, branch_ids=[main_branch.id], role='staff')

        assert resp.status_code == 302, "should redirect to user list on success"

    def test_admin_with_no_branches_saves(
        self, client, db_session, admin_user, main_branch
    ):
        """Admin role is exempt from the branch requirement."""
        _login_admin(client)
        target = User(username='tgt3', email='tgt3@test.com',
                      full_name='Target Three', role='viewer', is_active=True)
        target.set_password('Pass123!test')
        db_session.add(target)
        db_session.commit()

        resp = _edit_user_post(client, target, branch_ids=[], role='admin')

        assert resp.status_code == 302, "admin with no branches should save successfully"

    def test_viewer_with_no_branches_fails_validation(
        self, client, db_session, admin_user, main_branch
    ):
        """viewer role (another non-admin) is also rejected without branches."""
        _login_admin(client)
        target = User(username='tgt4', email='tgt4@test.com',
                      full_name='Target Four', role='viewer', is_active=True)
        target.set_password('Pass123!test')
        db_session.add(target)
        db_session.flush()
        target.branches.append(main_branch)
        db_session.commit()

        resp = _edit_user_post(client, target, branch_ids=[], role='viewer')

        assert resp.status_code == 200
        assert b'Assign at least one branch for non-admin roles.' in resp.data
