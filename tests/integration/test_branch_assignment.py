"""Integration tests for branch user assignment (B-009).

The branch-users page must operate on the user_branches many-to-many
relationship (the canonical source for branch access — has_branch_access(),
login branch selection), NOT the deprecated User.branch_id column:

- Assign via /branches/<id>/assign-user/<uid> grants real access (M2M row)
- Unassign via /branches/<id>/unassign-user/<uid> revokes real access
- Viewers are assignable (they cannot log in without a branch)
- Admins are not assignable (they have access to all branches automatically)
- Available list shows unassigned-to-this-branch users; assigned list reflects M2M
- Every assign/unassign writes an audit entry
"""
from app.users.models import User
from app.branches.models import Branch
from app.audit.models import AuditLog
import pytest
pytestmark = [pytest.mark.branches, pytest.mark.integration]




def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestBranchAssignment:
    def test_assign_creates_m2m_row_and_grants_access(self, client, db_session,
                                                      admin_user, viewer_user, main_branch):
        login(client)
        resp = client.post(f'/branches/{main_branch.id}/assign-user/{viewer_user.id}',
                           follow_redirects=True)
        assert resp.status_code == 200

        user = db_session.get(User, viewer_user.id)
        assert main_branch.id in user.get_branch_ids()
        assert user.has_branch_access(main_branch.id)

        audit = AuditLog.query.filter_by(module='branch', action='assign_user',
                                         record_id=main_branch.id).first()
        assert audit is not None
        assert audit.user_id == admin_user.id

    def test_assign_viewer_allowed(self, client, db_session, admin_user,
                                   viewer_user, main_branch):
        """Viewers need a branch to log in at all — they must be assignable."""
        login(client)
        client.post(f'/branches/{main_branch.id}/assign-user/{viewer_user.id}',
                    follow_redirects=True)
        assert viewer_user.has_branch_access(main_branch.id)

    def test_assign_admin_blocked(self, client, db_session, admin_user, main_branch):
        """Admins already have access to all branches; assigning them is rejected."""
        login(client)
        client.post(f'/branches/{main_branch.id}/assign-user/{admin_user.id}',
                    follow_redirects=True)
        assert main_branch.id not in admin_user.get_branch_ids()

    def test_unassign_removes_m2m_row_and_revokes_access(self, client, db_session,
                                                         admin_user, viewer_user, main_branch):
        login(client)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        assert viewer_user.has_branch_access(main_branch.id)

        resp = client.post(f'/branches/{main_branch.id}/unassign-user/{viewer_user.id}',
                           follow_redirects=True)
        assert resp.status_code == 200

        user = db_session.get(User, viewer_user.id)
        assert main_branch.id not in user.get_branch_ids()
        assert not user.has_branch_access(main_branch.id)

        audit = AuditLog.query.filter_by(module='branch', action='unassign_user',
                                         record_id=main_branch.id).first()
        assert audit is not None
        assert audit.user_id == admin_user.id

    def test_available_list_reflects_m2m_not_deprecated_fk(self, client, db_session,
                                                           admin_user, viewer_user,
                                                           accountant_user, main_branch):
        """A user with no user_branches row is available; an assigned user is not.
        The deprecated User.branch_id column must not drive the list."""
        login(client)
        accountant_user.add_branch(main_branch)
        # poison the deprecated column: it must be ignored
        viewer_user.branch_id = main_branch.id
        db_session.commit()

        resp = client.get(f'/branches/{main_branch.id}/users')
        html = resp.data.decode('utf-8')

        assigned, available = html.split('Available Users', 1)
        assert 'accountant@test.com' in assigned
        assert 'viewer@test.com' in available

    def test_assigned_user_not_in_available_list(self, client, db_session,
                                                 admin_user, viewer_user, main_branch):
        login(client)
        viewer_user.add_branch(main_branch)
        db_session.commit()

        resp = client.get(f'/branches/{main_branch.id}/users')
        html = resp.data.decode('utf-8')
        assigned, available = html.split('Available Users', 1)
        assert 'viewer@test.com' in assigned
        assert 'viewer@test.com' not in available

    def test_user_with_other_branch_still_available_here(self, client, db_session,
                                                         admin_user, viewer_user,
                                                         main_branch, branch_manila):
        """Multi-branch is supported: assignment to one branch must not hide the
        user from other branches' available lists."""
        login(client)
        viewer_user.add_branch(branch_manila)
        db_session.commit()

        resp = client.get(f'/branches/{main_branch.id}/users')
        html = resp.data.decode('utf-8')
        _, available = html.split('Available Users', 1)
        assert 'viewer@test.com' in available
