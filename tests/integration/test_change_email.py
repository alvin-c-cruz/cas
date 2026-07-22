"""Integration tests for self-service email change (R-11, User email editing)."""
import pytest
from app.users.models import User
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login_staff(client, db_session, staff_user, main_branch):
    """Non-admin users only see their OWN assigned branches (not "all"), so staff
    needs an explicit branch assignment before the before_request branch-session
    guard will let them past login to any page -- just requesting main_branch as
    a fixture param is not enough on its own."""
    staff_user.branches.append(main_branch)
    db_session.commit()
    client.post('/login', data={'username': 'staff', 'password': 'staff123'}, follow_redirects=True)


def test_change_email_page_renders(client, db_session, staff_user, main_branch):
    _login_staff(client, db_session, staff_user, main_branch)
    resp = client.get('/profile/change-email')
    assert resp.status_code == 200
    assert b'Current Password' in resp.data
    assert b'New Email' in resp.data


def test_profile_page_links_to_change_email(client, db_session, staff_user, main_branch):
    _login_staff(client, db_session, staff_user, main_branch)
    resp = client.get('/profile')
    assert resp.status_code == 200
    assert b'/profile/change-email' in resp.data


def test_change_email_succeeds_with_correct_password(client, db_session, staff_user, main_branch):
    _login_staff(client, db_session, staff_user, main_branch)
    resp = client.post('/profile/change-email', data={
        'current_password': 'staff123',
        'new_email': 'staff-new@test.com',
    }, follow_redirects=True)
    assert resp.status_code == 200

    updated = db_session.get(User, staff_user.id)
    assert updated.email == 'staff-new@test.com'


def test_change_email_rejected_with_wrong_password(client, db_session, staff_user, main_branch):
    _login_staff(client, db_session, staff_user, main_branch)
    client.post('/profile/change-email', data={
        'current_password': 'wrong-password',
        'new_email': 'staff-new@test.com',
    }, follow_redirects=True)

    unchanged = db_session.get(User, staff_user.id)
    assert unchanged.email == 'staff@test.com'


def test_change_email_rejected_when_already_taken(client, db_session, staff_user, main_branch, admin_user):
    _login_staff(client, db_session, staff_user, main_branch)
    client.post('/profile/change-email', data={
        'current_password': 'staff123',
        'new_email': admin_user.email,
    }, follow_redirects=True)

    unchanged = db_session.get(User, staff_user.id)
    assert unchanged.email == 'staff@test.com'


def test_change_email_audit_log_entry(client, db_session, staff_user, main_branch):
    _login_staff(client, db_session, staff_user, main_branch)
    client.post('/profile/change-email', data={
        'current_password': 'staff123',
        'new_email': 'staff-new@test.com',
    }, follow_redirects=True)

    audit = AuditLog.query.filter_by(module='users', action='change_email', record_id=staff_user.id).first()
    assert audit is not None


def test_change_email_rejected_when_reserved_by_pending_approved_email(client, db_session, staff_user, main_branch):
    """Guard: can't squat on an address an admin reserved for someone else's future
    registration -- an ApprovedEmail row that's approved but not yet used."""
    pending = ApprovedEmail(email='pending-hire@test.com', status='approved')
    db_session.add(pending)
    db_session.commit()

    _login_staff(client, db_session, staff_user, main_branch)
    client.post('/profile/change-email', data={
        'current_password': 'staff123',
        'new_email': 'pending-hire@test.com',
    }, follow_redirects=True)

    unchanged = db_session.get(User, staff_user.id)
    assert unchanged.email == 'staff@test.com'


def test_change_email_does_not_touch_original_approved_email_row(client, db_session, staff_user, main_branch):
    """Rule #2: changing email must NOT free the ApprovedEmail row consumed at registration."""
    approved = ApprovedEmail(email='staff@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved.mark_as_used(staff_user.id)

    _login_staff(client, db_session, staff_user, main_branch)
    client.post('/profile/change-email', data={
        'current_password': 'staff123',
        'new_email': 'staff-new@test.com',
    }, follow_redirects=True)

    reloaded = db_session.get(ApprovedEmail, approved.id)
    assert reloaded.is_used is True
    assert reloaded.used_by_user_id == staff_user.id
