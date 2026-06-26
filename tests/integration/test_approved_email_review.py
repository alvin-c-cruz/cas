"""Integration tests for the approved-email review flow (approve/reject)
and action-items badge count.

Admin approves/rejects a pending request; accountant sees read-only list.
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


def _seed_pending(db_session, accountant_user):
    """Insert a pending ApprovedEmail row."""
    from app.users.approved_emails import ApprovedEmail
    ae = ApprovedEmail(
        email='pending@review.ph',
        status='pending',
        requested_by_user_id=accountant_user.id,
    )
    db_session.add(ae)
    db_session.commit()
    return ae


# ---------------------------------------------------------------------------
# Admin approve
# ---------------------------------------------------------------------------

def test_admin_approve_sets_approved_and_notifies(
        client, db_session, admin_user, accountant_user, main_branch):
    """POST /approved-emails/<id>/approve → status=approved; accountant notified; audit logged."""
    from app.users.approved_emails import ApprovedEmail

    ae = _seed_pending(db_session, accountant_user)
    _login(client, admin_user, main_branch, 'admin123')

    resp = client.post(f'/approved-emails/{ae.id}/approve',
                       data={},
                       follow_redirects=False)
    assert resp.status_code == 302

    db_session.refresh(ae)
    assert ae.status == 'approved'

    notif = Notification.query.filter_by(
        user_id=accountant_user.id,
        related_type='approved_email',
        related_id=ae.id,
        category='success',
    ).first()
    assert notif is not None

    audit = AuditLog.query.filter_by(
        module='approved_email',
        action='approve',
        record_id=ae.id,
    ).first()
    assert audit is not None
    assert audit.user_id == admin_user.id


def test_approved_email_now_registerable(
        client, db_session, admin_user, accountant_user, main_branch):
    """After approval, is_email_approved returns True."""
    from app.users.approved_emails import ApprovedEmail

    ae = _seed_pending(db_session, accountant_user)
    _login(client, admin_user, main_branch, 'admin123')
    client.post(f'/approved-emails/{ae.id}/approve', data={}, follow_redirects=False)

    assert ApprovedEmail.is_email_approved('pending@review.ph') is True


# ---------------------------------------------------------------------------
# Admin reject
# ---------------------------------------------------------------------------

def test_admin_reject_sets_rejected_and_notifies(
        client, db_session, admin_user, accountant_user, main_branch):
    """POST /approved-emails/<id>/reject with reason → status=rejected; accountant notified (error); audit."""
    from app.users.approved_emails import ApprovedEmail

    ae = _seed_pending(db_session, accountant_user)
    _login(client, admin_user, main_branch, 'admin123')

    # Need CSRF token - get it from a GET first
    resp_get = client.get('/approved-emails')
    assert resp_get.status_code == 200

    resp = client.post(f'/approved-emails/{ae.id}/reject',
                       data={'reason': 'dupe'},
                       follow_redirects=False)
    assert resp.status_code == 302

    db_session.refresh(ae)
    assert ae.status == 'rejected'
    assert 'dupe' in (ae.notes or '')

    notif = Notification.query.filter_by(
        user_id=accountant_user.id,
        related_type='approved_email',
        related_id=ae.id,
        category='error',
    ).first()
    assert notif is not None

    audit = AuditLog.query.filter_by(
        module='approved_email',
        action='reject',
        record_id=ae.id,
    ).first()
    assert audit is not None
    assert audit.user_id == admin_user.id

    from app.users.approved_emails import ApprovedEmail
    assert ApprovedEmail.is_email_approved('pending@review.ph') is False


# ---------------------------------------------------------------------------
# Accountant cannot approve/reject
# ---------------------------------------------------------------------------

def test_accountant_cannot_approve(
        client, db_session, admin_user, accountant_user, main_branch):
    """Accountant POST /approve is denied; status remains pending."""
    from app.users.approved_emails import ApprovedEmail

    ae = _seed_pending(db_session, accountant_user)
    _login(client, accountant_user, main_branch, 'accountant123')

    resp = client.post(f'/approved-emails/{ae.id}/approve', data={}, follow_redirects=False)
    # Should be denied → redirect (not 200)
    assert resp.status_code == 302

    db_session.refresh(ae)
    assert ae.status == 'pending'


# ---------------------------------------------------------------------------
# Accountant read-only list
# ---------------------------------------------------------------------------

def test_accountant_sees_list_readonly(
        client, db_session, admin_user, accountant_user, main_branch):
    """Accountant GET /approved-emails returns 200; shows status but no approve/reject actions."""
    import re
    _seed_pending(db_session, accountant_user)
    _login(client, accountant_user, main_branch, 'accountant123')

    resp = client.get('/approved-emails', follow_redirects=False)
    assert resp.status_code == 200

    body = resp.data.decode()
    # Must NOT contain an approve POST form action (route is /approved-emails/<id>/approve)
    assert re.search(r'/approved-emails/\d+/approve', body) is None, \
        "Accountant should not see approve form actions"
    # Must NOT contain a reject POST form action
    assert re.search(r'/approved-emails/\d+/reject', body) is None, \
        "Accountant should not see reject form actions"
    # Must show the status
    assert 'Pending' in body or 'pending' in body.lower()


# ---------------------------------------------------------------------------
# Action-items count
# ---------------------------------------------------------------------------

def test_action_items_counts_pending_request(db_session, admin_user, accountant_user, main_branch):
    """A pending approved-email row is included in the admin action-items count."""
    from app.dashboard.action_items_service import count_action_items

    _seed_pending(db_session, accountant_user)

    count = count_action_items(admin_user, main_branch.id)
    assert count >= 1, "Pending approved-email requests must appear in the admin action-items count"
