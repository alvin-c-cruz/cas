"""Integration tests for approved-email pre-registration management.

- Admin can add an approved email; row created and audit entry written
- Admin can delete an unused approved email; audit entry written
- Non-admin users are blocked
"""
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestApprovedEmails:
    def test_admin_add_creates_row_and_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/approved-emails/add', data={
            'email': 'new.hire@example.com',
            'notes': 'New accountant',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'has been approved for registration' in resp.data

        row = ApprovedEmail.query.filter_by(email='new.hire@example.com').first()
        assert row is not None
        assert row.approved_by_user_id == admin_user.id
        assert row.is_used is False

        audit = AuditLog.query.filter_by(module='approved_email', action='create',
                                         record_id=row.id).first()
        assert audit is not None
        assert audit.record_identifier == 'new.hire@example.com'
        assert audit.user_id == admin_user.id

    def test_admin_delete_unused_writes_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        client.post('/approved-emails/add', data={'email': 'temp@example.com', 'notes': ''},
                    follow_redirects=True)
        row = ApprovedEmail.query.filter_by(email='temp@example.com').first()
        row_id = row.id

        resp = client.post(f'/approved-emails/{row_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert b'has been removed' in resp.data
        assert ApprovedEmail.query.get(row_id) is None

        audit = AuditLog.query.filter_by(module='approved_email', action='delete',
                                         record_id=row_id).first()
        assert audit is not None
        assert audit.record_identifier == 'temp@example.com'
        assert audit.user_id == admin_user.id

    def test_non_admin_blocked(self, client, db_session, accountant_user, staff_user, main_branch):
        login(client, username='staff', password='staff123')
        resp = client.post('/approved-emails/add', data={
            'email': 'sneaky@example.com', 'notes': '',
        }, follow_redirects=True)
        assert ApprovedEmail.query.filter_by(email='sneaky@example.com').first() is None
