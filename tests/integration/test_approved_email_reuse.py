"""Integration tests for ApprovedEmail reuse rules (R-11, User email editing).

Rule #3: reusing a previously-used approved email requires an explicit admin
action -- delete the used row, then re-add fresh. Rule #4: adding an approved
email is blocked if that address already belongs to an existing User.
"""
import pytest
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_admin_can_delete_a_used_approved_email(client, db_session, admin_user, main_branch):
    approved = ApprovedEmail(email='reused@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved.mark_as_used(admin_user.id)
    approved_id = approved.id

    _login(client, 'admin', 'admin123')
    resp = client.post(f'/approved-emails/{approved_id}/delete', follow_redirects=True)
    assert resp.status_code == 200

    assert db_session.get(ApprovedEmail, approved_id) is None


def test_deleting_an_unused_approved_email_still_works(client, db_session, admin_user, main_branch):
    """Regression: the existing unused-row delete path is unaffected."""
    approved = ApprovedEmail(email='unused@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved_id = approved.id

    _login(client, 'admin', 'admin123')
    resp = client.post(f'/approved-emails/{approved_id}/delete', follow_redirects=True)
    assert resp.status_code == 200

    assert db_session.get(ApprovedEmail, approved_id) is None


def test_deleting_a_used_approved_email_is_audited(client, db_session, admin_user, main_branch):
    approved = ApprovedEmail(email='reused2@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved.mark_as_used(admin_user.id)
    approved_id = approved.id

    _login(client, 'admin', 'admin123')
    client.post(f'/approved-emails/{approved_id}/delete', follow_redirects=True)

    audit = AuditLog.query.filter_by(module='approved_email', action='delete', record_id=approved_id).first()
    assert audit is not None


def test_reapproving_a_freed_email_creates_a_fresh_unused_row(client, db_session, admin_user, main_branch):
    approved = ApprovedEmail(email='reused3@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved.mark_as_used(admin_user.id)
    approved_id = approved.id

    _login(client, 'admin', 'admin123')
    client.post(f'/approved-emails/{approved_id}/delete', follow_redirects=True)

    resp = client.post('/approved-emails/add', data={
        'email': 'reused3@test.com', 'position': 'staff', 'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    fresh = ApprovedEmail.query.filter_by(email='reused3@test.com').first()
    assert fresh is not None
    assert fresh.is_used is False


def test_cannot_add_approved_email_for_an_existing_user(client, db_session, admin_user, staff_user, main_branch):
    """Guard #4: an approved-email row can't be added for an address that's already a User."""
    _login(client, 'admin', 'admin123')
    resp = client.post('/approved-emails/add', data={
        'email': staff_user.email, 'position': 'staff', 'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    assert ApprovedEmail.query.filter_by(email=staff_user.email).first() is None


def test_can_still_add_a_genuinely_new_approved_email(client, db_session, admin_user, main_branch):
    """Regression: guard #4 doesn't block a legitimately new address."""
    _login(client, 'admin', 'admin123')
    resp = client.post('/approved-emails/add', data={
        'email': 'brand-new@test.com', 'position': 'staff', 'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    assert ApprovedEmail.query.filter_by(email='brand-new@test.com').first() is not None
