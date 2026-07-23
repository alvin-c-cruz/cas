"""Editing your OWN user profile must not false-reject with "You cannot deactivate
your own account" (or the analogous role guard) when is_active/role are simply
absent from the POST body -- exactly what a real browser sends for a field
rendered disabled=true (BUG-EDITUSER-SELF-EDIT-DISABLED-CHECKBOX-FALSE-REJECT).

A disabled HTML field is never included in the browser's submitted form data,
regardless of its checked/selected state -- these tests omit 'is_active' and
'role' from the POST payload entirely to faithfully reproduce that, rather than
sending them (which a real disabled checkbox/select never does).
"""
import pytest
from app.users.models import User

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


class TestSelfEditDisabledFields:
    def test_self_edit_with_is_active_and_role_omitted_succeeds(self, client, db_session, admin_user, main_branch):
        """Mirrors what a real browser submits for a self-edit: is_active and role
        are both absent (disabled fields), everything else present."""
        _login(client, 'admin', 'admin123')
        resp = client.post(f'/users/{admin_user.id}/edit', data={
            'username': 'admin', 'email': admin_user.email, 'full_name': 'Alvin Cruz Updated',
            'branch_ids': [str(main_branch.id)],
            # is_active and role deliberately OMITTED -- what a disabled field submits
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'You cannot deactivate your own account' not in resp.data
        assert b'You cannot change your own role' not in resp.data

        updated = db_session.get(User, admin_user.id)
        assert updated.full_name == 'Alvin Cruz Updated'

    def test_self_edit_preserves_is_active_true(self, client, db_session, admin_user, main_branch):
        _login(client, 'admin', 'admin123')
        assert admin_user.is_active is True
        client.post(f'/users/{admin_user.id}/edit', data={
            'username': 'admin', 'email': admin_user.email, 'full_name': admin_user.full_name,
            'branch_ids': [str(main_branch.id)],
        }, follow_redirects=True)

        updated = db_session.get(User, admin_user.id)
        assert updated.is_active is True

    def test_self_edit_preserves_own_role(self, client, db_session, admin_user, main_branch):
        _login(client, 'admin', 'admin123')
        assert admin_user.role == 'admin'
        client.post(f'/users/{admin_user.id}/edit', data={
            'username': 'admin', 'email': admin_user.email, 'full_name': admin_user.full_name,
            'branch_ids': [str(main_branch.id)],
        }, follow_redirects=True)

        updated = db_session.get(User, admin_user.id)
        assert updated.role == 'admin'

    def test_self_edit_can_update_branch_assignments(self, client, db_session, admin_user, main_branch, branch_manila):
        """The concrete scenario that surfaced this bug: assigning yourself to
        another branch via Edit User."""
        _login(client, 'admin', 'admin123')
        # Admin can access both branches, so the branch-session hook won't
        # auto-select -- pin one or the request redirects to the picker.
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.post(f'/users/{admin_user.id}/edit', data={
            'username': 'admin', 'email': admin_user.email, 'full_name': admin_user.full_name,
            'branch_ids': [str(main_branch.id), str(branch_manila.id)],
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'You cannot deactivate your own account' not in resp.data

        updated = db_session.get(User, admin_user.id)
        assert sorted(updated.get_branch_ids()) == sorted([main_branch.id, branch_manila.id])

    def test_editing_another_user_still_honors_submitted_is_active_and_role(self, client, db_session, admin_user, staff_user, main_branch):
        """Regression guard: the self-edit-only override must not leak into editing
        OTHER users, where is_active/role remain fully editable and submitted."""
        _login(client, 'admin', 'admin123')
        resp = client.post(f'/users/{staff_user.id}/edit', data={
            'username': 'staff', 'email': staff_user.email, 'full_name': staff_user.full_name,
            'role': 'accountant', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200

        updated = db_session.get(User, staff_user.id)
        assert updated.role == 'accountant'
        assert updated.is_active is True

    def test_editing_another_user_can_still_deactivate_them(self, client, db_session, admin_user, staff_user, main_branch):
        _login(client, 'admin', 'admin123')
        client.post(f'/users/{staff_user.id}/edit', data={
            'username': 'staff', 'email': staff_user.email, 'full_name': staff_user.full_name,
            'role': 'staff', 'branch_ids': [str(main_branch.id)],
            # is_active omitted (unchecked) -- a real, intentional deactivation of ANOTHER user
        }, follow_redirects=True)

        updated = db_session.get(User, staff_user.id)
        assert updated.is_active is False
