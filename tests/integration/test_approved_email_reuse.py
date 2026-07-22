"""Integration tests for ApprovedEmail reuse rules (R-11, User email editing).

Rule #3: reusing a previously-used approved email requires an explicit admin
action -- delete the used row, then re-add fresh. Rule #4: adding an approved
email is blocked if that address already belongs to an existing User.
"""
import pytest
from app.users.models import User
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_approved_emails_list_renders_delete_button_for_a_used_row(client, db_session, admin_user, main_branch):
    """Render-assertion regression pin for BUG-APPROVEDEMAIL-DELETE-BUTTON-HIDDEN-WHEN-USED:
    the backend allowing a used row to be deleted is not provable by a POST-contract test
    (every test below POSTs the delete URL directly) -- only a GET render assertion catches
    the template still hiding the button, which is exactly how this one shipped invisible to
    the pytest suite and was only found in the live pre-merge browser pass."""
    approved = ApprovedEmail(email='reused-render@test.com', status='approved')
    db_session.add(approved)
    db_session.commit()
    approved.mark_as_used(admin_user.id)

    _login(client, 'admin', 'admin123')
    resp = client.get('/approved-emails')
    assert resp.status_code == 200
    assert f'/approved-emails/{approved.id}/delete'.encode() in resp.data


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


def test_full_approved_email_reuse_lifecycle(client, db_session, admin_user, main_branch):
    """End-to-end pin of the composed Rule #3 lifecycle.

    Every piece is already tested in isolation across Tasks 1-3 (a self-service
    email change doesn't free the original ApprovedEmail row; an admin can
    delete a used row; a freed email can be re-approved fresh). This test walks
    the FULL chain in one go and asserts there is no collision between the two
    distinct users who, at different points in time, both hold/held the same
    approved address:

      register user1 against an approved email
        -> that row is marked used
        -> user1 self-service-changes their email away from it
        -> admin deletes the now-orphaned original ApprovedEmail row
        -> admin re-approves that same address fresh
        -> a SECOND user registers with it
        -> both Users are distinct rows; user1's id and current (changed)
           email are unaffected; no collision.
    """
    reused_email = 'lifecycle@test.com'
    password1 = 'Sup3rSecret!23'
    password2 = 'Anoth3rSecret!45'

    # 1. Admin pre-approves the address for a staff hire.
    approved = ApprovedEmail(email=reused_email, status='approved', role='staff')
    approved.branches = [main_branch]
    db_session.add(approved)
    db_session.commit()
    approved_id = approved.id

    # 2. User 1 registers against it -> the row is marked used.
    resp = client.post('/register', data={
        'username': 'lifecycle1',
        'email': reused_email,
        'full_name': 'Lifecycle One',
        'password': password1,
        'confirm_password': password1,
    }, follow_redirects=True)
    assert resp.status_code == 200

    user1 = User.query.filter_by(username='lifecycle1').first()
    assert user1 is not None
    assert user1.email == reused_email
    user1_id = user1.id

    db_session.refresh(approved)
    assert approved.is_used is True
    assert approved.used_by_user_id == user1_id

    # 3. User 1 self-service changes their email away from the approved address.
    client.post('/login', data={'username': 'lifecycle1', 'password': password1}, follow_redirects=True)
    resp = client.post('/profile/change-email', data={
        'current_password': password1,
        'new_email': 'lifecycle1-new@test.com',
    }, follow_redirects=True)
    assert resp.status_code == 200

    user1 = db_session.get(User, user1_id)
    assert user1.email == 'lifecycle1-new@test.com'

    # Rule #2: the original ApprovedEmail row is untouched by the email change --
    # it stays used, now orphaned (points at a user who no longer holds that email).
    db_session.refresh(approved)
    assert approved.is_used is True
    assert approved.used_by_user_id == user1_id

    client.get('/logout')

    # 4. Admin deletes the now-orphaned original ApprovedEmail row.
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/approved-emails/{approved_id}/delete', follow_redirects=True)
    assert resp.status_code == 200
    assert db_session.get(ApprovedEmail, approved_id) is None

    # 5. Admin re-approves the same address, fresh.
    resp = client.post('/approved-emails/add', data={
        'email': reused_email, 'position': 'staff', 'notes': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    fresh = ApprovedEmail.query.filter_by(email=reused_email).first()
    assert fresh is not None
    assert fresh.is_used is False

    client.get('/logout')

    # 6. A SECOND, distinct user registers with the freed address.
    resp = client.post('/register', data={
        'username': 'lifecycle2',
        'email': reused_email,
        'full_name': 'Lifecycle Two',
        'password': password2,
        'confirm_password': password2,
    }, follow_redirects=True)
    assert resp.status_code == 200

    user2 = User.query.filter_by(username='lifecycle2').first()
    assert user2 is not None
    assert user2.email == reused_email

    # 7. No collision: two distinct User rows, user1 unaffected by user2's registration.
    assert user2.id != user1_id
    user1 = db_session.get(User, user1_id)
    assert user1.id == user1_id
    assert user1.email == 'lifecycle1-new@test.com'
    assert User.query.filter_by(email=reused_email).count() == 1
    assert User.query.filter_by(email='lifecycle1-new@test.com').count() == 1
