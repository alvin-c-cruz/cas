"""Integration tests for the approved-email submit flow.

Accountant submits a pending request; admin submits directly to approved.
"""
import pytest
from app.audit.models import AuditLog
from app.notifications.models import Notification

pytestmark = [pytest.mark.integration]


def _login(client, user, branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def _post_add(client, email, notes='', position='viewer', branch_ids=None):
    # Feature B made position required; branch is auto-assigned when the approver
    # has a single branch (the case in these tests), so branch_ids may be omitted.
    data = {'email': email, 'notes': notes, 'position': position}
    if branch_ids is not None:
        data['branch_ids'] = [str(b) for b in branch_ids]
    return client.post('/approved-emails/add', data=data, follow_redirects=False)


# ---------------------------------------------------------------------------
# accountant submit → pending
# ---------------------------------------------------------------------------

def test_accountant_submit_creates_pending(client, db_session, admin_user, accountant_user, main_branch):
    """Accountant POSTing to /approved-emails/add creates a pending row."""
    from app.users.approved_emails import ApprovedEmail

    _login(client, accountant_user, main_branch, 'accountant123')
    resp = _post_add(client, 'new@example.ph')

    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='new@example.ph').first()
    assert ae is not None
    assert ae.status == 'pending'
    assert ae.requested_by_user_id == accountant_user.id
    assert ae.approved_by_user_id is None


def test_accountant_submit_notifies_admins(client, db_session, admin_user, accountant_user, main_branch):
    """After accountant submit, each admin receives an in-app notification."""
    _login(client, accountant_user, main_branch, 'accountant123')
    _post_add(client, 'notify@example.ph')

    from app.users.approved_emails import ApprovedEmail
    ae = ApprovedEmail.query.filter_by(email='notify@example.ph').first()
    assert ae is not None

    notif = Notification.query.filter_by(
        user_id=admin_user.id,
        related_type='approved_email',
        related_id=ae.id
    ).first()
    assert notif is not None


def test_accountant_submit_audited(client, db_session, admin_user, accountant_user, main_branch):
    """Accountant submit produces an AuditLog row with action='request'."""
    _login(client, accountant_user, main_branch, 'accountant123')
    _post_add(client, 'audit@example.ph')

    from app.users.approved_emails import ApprovedEmail
    ae = ApprovedEmail.query.filter_by(email='audit@example.ph').first()
    assert ae is not None

    audit = AuditLog.query.filter_by(
        module='approved_email',
        action='request',
        record_id=ae.id,
    ).first()
    assert audit is not None
    assert audit.user_id == accountant_user.id


# ---------------------------------------------------------------------------
# admin submit → approved immediately
# ---------------------------------------------------------------------------

def test_admin_submit_creates_approved(client, db_session, admin_user, main_branch):
    """Admin POSTing to /approved-emails/add creates an approved row immediately."""
    from app.users.approved_emails import ApprovedEmail

    _login(client, admin_user, main_branch, 'admin123')
    resp = _post_add(client, 'admin_direct@example.ph')

    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='admin_direct@example.ph').first()
    assert ae is not None
    assert ae.status == 'approved'
    assert ae.approved_by_user_id == admin_user.id


# ---------------------------------------------------------------------------
# role gate
# ---------------------------------------------------------------------------

def test_staff_cannot_submit(client, db_session, staff_user, main_branch):
    """Staff GET /approved-emails/add is denied (redirect, not 200 form)."""
    _login(client, staff_user, main_branch, 'staff123')
    resp = client.get('/approved-emails/add', follow_redirects=False)
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# GET renders the form (regression: the template defined {% block title %}
# twice via if/else, which Jinja rejects at compile time — a successful POST
# redirects so the earlier tests never rendered it)
# ---------------------------------------------------------------------------

def test_add_form_get_renders_for_admin(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.get('/approved-emails/add')
    assert resp.status_code == 200
    assert b'Add Approved Email' in resp.data


def test_request_form_get_renders_for_accountant(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = client.get('/approved-emails/add')
    assert resp.status_code == 200
    assert b'Request Email Approval' in resp.data
