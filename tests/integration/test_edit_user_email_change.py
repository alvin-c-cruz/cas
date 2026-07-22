"""Integration tests for the admin edit_user email-change fallback (R-11, User email editing).

Mirrors tests/integration/test_edit_user_optional_perms.py's payload pattern.
"""
import json
import pytest
from app.users.models import User
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _edit_payload(main_branch, **overrides):
    data = {
        'username': 'staff', 'email': 'staff@test.com', 'full_name': 'Staff User',
        'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
    }
    data.update(overrides)
    return data


def test_admin_can_change_a_users_email(client, db_session, admin_user, staff_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit', data=_edit_payload(
        main_branch, email='staff-new@test.com'
    ), follow_redirects=True)
    assert resp.status_code == 200

    updated = db_session.get(User, staff_user.id)
    assert updated.email == 'staff-new@test.com'


def test_admin_edit_rejects_duplicate_email(client, db_session, admin_user, staff_user, main_branch):
    _login(client, 'admin', 'admin123')
    client.post(f'/users/{staff_user.id}/edit', data=_edit_payload(
        main_branch, email=admin_user.email
    ), follow_redirects=True)

    unchanged = db_session.get(User, staff_user.id)
    assert unchanged.email == 'staff@test.com'


def test_admin_edit_email_change_is_audited(client, db_session, admin_user, staff_user, main_branch):
    _login(client, 'admin', 'admin123')
    client.post(f'/users/{staff_user.id}/edit', data=_edit_payload(
        main_branch, email='staff-new@test.com'
    ), follow_redirects=True)

    audit = AuditLog.query.filter_by(
        module='user', action='update', record_id=staff_user.id
    ).order_by(AuditLog.id.desc()).first()
    assert audit is not None
    assert json.loads(audit.old_values)['email'] == 'staff@test.com'
    assert json.loads(audit.new_values)['email'] == 'staff-new@test.com'


def test_edit_form_email_field_is_editable_username_stays_locked(client, db_session, admin_user, staff_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/users/{staff_user.id}/edit')
    assert resp.status_code == 200
    assert b'Email cannot be changed after account creation' not in resp.data
    assert b'Username cannot be changed after account creation' in resp.data
