"""Integration tests for Feature B — registration consumes the ApprovedEmail's
stamped role + branches (active path), with a legacy fallback for null-role rows."""
import pytest
from app.users.models import User
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _register(client, username, email, password='Sup3rSecret!23'):
    return client.post('/register', data={
        'username': username,
        'email': email,
        'full_name': 'New Person',
        'password': password,
        'confirm_password': password,
    }, follow_redirects=False)


def test_register_stamped_email_creates_active_user(client, db_session, main_branch, branch_manila):
    """A role-stamped approved email yields an active user with that role + branches."""
    ae = ApprovedEmail(email='hire@example.ph', status='approved', role='staff')
    ae.branches = [main_branch, branch_manila]
    db_session.add(ae)
    db_session.commit()

    resp = _register(client, 'newstaff', 'hire@example.ph')
    assert resp.status_code == 302

    user = User.query.filter_by(email='hire@example.ph').first()
    assert user is not None
    assert user.is_active is True
    assert user.role == 'staff'
    assert sorted(user.get_branch_ids()) == sorted([main_branch.id, branch_manila.id])

    db_session.refresh(ae)
    assert ae.is_used is True
    assert ae.used_by_user_id == user.id

    audit = AuditLog.query.filter_by(module='user_registration', action='registration_success',
                                     record_id=user.id).first()
    assert audit is not None


def test_register_stamped_user_can_login(client, db_session, main_branch):
    """The active registrant can immediately log in (no pending-approval block)."""
    ae = ApprovedEmail(email='loginme@example.ph', status='approved', role='viewer')
    ae.branches = [main_branch]
    db_session.add(ae)
    db_session.commit()

    _register(client, 'loginme', 'loginme@example.ph', password='Sup3rSecret!23')
    resp = client.post('/login', data={'username': 'loginme', 'password': 'Sup3rSecret!23'},
                       follow_redirects=False)
    # Single accessible branch → auto-selected → redirect to dashboard, not back to login.
    assert resp.status_code == 302
    assert '/login' not in resp.headers.get('Location', '')


def test_register_legacy_email_stays_viewer_inactive(client, db_session, main_branch):
    """A legacy approved email (role=None) keeps the original viewer/inactive behavior."""
    ae = ApprovedEmail(email='legacy@example.ph', status='approved', role=None)
    db_session.add(ae)
    db_session.commit()

    resp = _register(client, 'legacyuser', 'legacy@example.ph')
    assert resp.status_code == 302

    user = User.query.filter_by(email='legacy@example.ph').first()
    assert user is not None
    assert user.role == 'viewer'
    assert user.is_active is False
    assert user.get_branch_ids() == []
