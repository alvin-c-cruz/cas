"""B-1: accountant email self-approval behavior, gated by the company toggle."""
import pytest
from app.settings import AppSettings
from app.users.models import User
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog
from app.notifications.models import Notification

pytestmark = [pytest.mark.integration]


def _login(client, user, branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def _submit(client, email, position):
    # single-branch accountant → branch auto-assigned, branch_ids omitted
    return client.post('/approved-emails/add',
                       data={'email': email, 'position': position, 'notes': ''},
                       follow_redirects=False)


def test_toggle_off_accountant_request_is_pending(client, db_session, admin_user,
                                                  accountant_user, main_branch):
    # default off
    _login(client, accountant_user, main_branch, 'accountant123')
    _submit(client, 'off@example.ph', 'staff')
    ae = ApprovedEmail.query.filter_by(email='off@example.ph').first()
    assert ae.status == 'pending'
    assert ae.approved_by_user_id is None


def test_toggle_on_viewer_is_self_approved(client, db_session, admin_user,
                                           accountant_user, main_branch):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    _login(client, accountant_user, main_branch, 'accountant123')
    _submit(client, 'selfview@example.ph', 'viewer')
    ae = ApprovedEmail.query.filter_by(email='selfview@example.ph').first()
    assert ae.status == 'approved'
    assert ae.approved_by_user_id == accountant_user.id


def test_toggle_on_staff_is_self_approved(client, db_session, admin_user,
                                          accountant_user, main_branch):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    _login(client, accountant_user, main_branch, 'accountant123')
    _submit(client, 'self@example.ph', 'staff')

    ae = ApprovedEmail.query.filter_by(email='self@example.ph').first()
    assert ae.status == 'approved'
    assert ae.approved_by_user_id == accountant_user.id
    # FYI notification to the admin
    notif = Notification.query.filter_by(user_id=admin_user.id, related_type='approved_email',
                                         related_id=ae.id).first()
    assert notif is not None
    assert 'self-approved' in notif.message.lower()
    # audit row
    audit = AuditLog.query.filter_by(module='approved_email', action='create',
                                     record_id=ae.id).first()
    assert audit is not None


def test_toggle_on_accountant_position_still_pending(client, db_session, admin_user,
                                                     accountant_user, main_branch):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    _login(client, accountant_user, main_branch, 'accountant123')
    _submit(client, 'peer@example.ph', 'accountant')   # guardrail
    ae = ApprovedEmail.query.filter_by(email='peer@example.ph').first()
    assert ae.status == 'pending'
    assert ae.approved_by_user_id is None


def test_self_approved_email_registers_active_user(client, db_session, admin_user,
                                                   accountant_user, main_branch):
    AppSettings.set_setting('accountant_email_self_approval', '1')
    _login(client, accountant_user, main_branch, 'accountant123')
    _submit(client, 'reg@example.ph', 'staff')
    # clear the accountant session before registering as the new user
    client.get('/logout', follow_redirects=True)
    resp = client.post('/register', data={
        'username': 'reguser', 'email': 'reg@example.ph', 'full_name': 'Reg User',
        'password': 'Sup3rSecret!23', 'confirm_password': 'Sup3rSecret!23',
    }, follow_redirects=False)
    assert resp.status_code == 302
    user = User.query.filter_by(email='reg@example.ph').first()
    assert user is not None and user.is_active is True and user.role == 'staff'
