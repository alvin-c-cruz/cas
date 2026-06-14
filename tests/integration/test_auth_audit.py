"""Auth audit quality (B-004) and user-edit audit noise.

- login_success rows must carry the user's id even though the audit fires
  before login_user() (current_user is still anonymous at that point)
- editing a user without touching book permissions must NOT write a
  permission_granted row (empty stored permissions == all-False form dict)
"""
from app.audit.models import AuditLog
import pytest
pytestmark = [pytest.mark.users, pytest.mark.audit, pytest.mark.integration]




class TestAuthAudit:
    def test_login_success_has_user_id(self, client, db_session, admin_user, main_branch):
        client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                    follow_redirects=True)
        row = (AuditLog.query.filter_by(module='auth', action='login_success')
               .order_by(AuditLog.id.desc()).first())
        assert row is not None
        assert row.user_id == admin_user.id

    def test_auto_branch_selection_is_audited(self, client, db_session,
                                              viewer_user, main_branch):
        viewer_user.add_branch(main_branch)
        db_session.commit()
        client.post('/login', data={'username': 'viewer', 'password': 'viewer123'},
                    follow_redirects=True)
        row = (AuditLog.query.filter_by(module='auth', action='branch_selected')
               .order_by(AuditLog.id.desc()).first())
        assert row is not None
        assert 'Auto-selected' in row.notes

    def test_user_edit_without_permission_change_writes_no_permission_row(
            self, client, db_session, admin_user, viewer_user, main_branch):
        client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                    follow_redirects=True)
        resp = client.post(f'/users/{viewer_user.id}/edit', data={
            'username': viewer_user.username,
            'email': viewer_user.email,
            'full_name': viewer_user.full_name,
            'role': 'viewer',
            'is_active': 'y',
            'branch_ids': [str(main_branch.id)],
        }, follow_redirects=True)
        assert resp.status_code == 200
        rows = AuditLog.query.filter(
            AuditLog.module == 'user',
            AuditLog.action.in_(['permission_granted', 'permission_revoked']),
            AuditLog.record_id == viewer_user.id,
        ).all()
        assert rows == []
