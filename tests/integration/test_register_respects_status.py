"""Integration tests: /register honours the ApprovedEmail status gate.

pending/rejected emails cannot register; approved emails can.
"""
import pytest

pytestmark = [pytest.mark.integration]


def _seed_email(db_session, email, status='approved', approved_by_id=None, requested_by_id=None):
    from app.users.approved_emails import ApprovedEmail
    ae = ApprovedEmail(
        email=email,
        status=status,
        approved_by_user_id=approved_by_id,
        requested_by_user_id=requested_by_id,
    )
    db_session.add(ae)
    db_session.commit()
    return ae


def _register(client, email, username='newuser'):
    return client.post('/register', data={
        'username': username,
        'email': email,
        'full_name': 'Test User',
        'password': 'SecureP@ss1234',
        'confirm_password': 'SecureP@ss1234',
    }, follow_redirects=False)


def test_register_blocked_for_pending_email(client, db_session, admin_user):
    """A pending email cannot be used for registration — returns 200 re-render, no user created."""
    from app.users.models import User

    _seed_email(db_session, 'pending@block.ph', status='pending', requested_by_id=admin_user.id)

    resp = _register(client, 'pending@block.ph', username='pendinguser')
    # Form re-rendered (not a redirect) → email validation failed
    assert resp.status_code == 200

    user = User.query.filter_by(email='pending@block.ph').first()
    assert user is None, 'A pending email must not allow registration'


def test_register_blocked_for_rejected_email(client, db_session, admin_user):
    """A rejected email cannot register either."""
    from app.users.models import User

    _seed_email(db_session, 'rejected@block.ph', status='rejected', approved_by_id=admin_user.id)

    resp = _register(client, 'rejected@block.ph', username='rejecteduser')
    assert resp.status_code == 200

    user = User.query.filter_by(email='rejected@block.ph').first()
    assert user is None, 'A rejected email must not allow registration'


def test_register_ok_for_approved_email(client, db_session, admin_user):
    """An approved, unused email allows registration; new user is created as viewer."""
    from app.users.models import User

    _seed_email(db_session, 'ok@reg.ph', status='approved', approved_by_id=admin_user.id)

    resp = _register(client, 'ok@reg.ph', username='okuser')
    # Successful registration redirects to login
    assert resp.status_code == 302

    user = User.query.filter_by(email='ok@reg.ph').first()
    assert user is not None
    assert user.role == 'viewer'
    assert user.is_active is False  # new registrations require admin activation
