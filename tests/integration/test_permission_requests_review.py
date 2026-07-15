import pytest
from app import db
from app.permission_requests.models import PermissionChangeRequest
from app.notifications.models import Notification

pytestmark = pytest.mark.integration


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.fixture
def limited_accountant(db_session, main_branch):
    from app.users.models import User
    user = User(
        username='limited_accountant', email='limited@test.com',
        full_name='Limited Accountant', role='accountant', is_active=True,
    )
    user.set_password('limited123')
    user.set_book_permissions({'vendors': True})
    db.session.add(user)
    db.session.flush()
    user.set_branches([main_branch])
    db.session.commit()
    return user


@pytest.fixture
def pending_request(db_session, limited_accountant, chief_accountant_user):
    req = PermissionChangeRequest(
        target_user_id=limited_accountant.id, requested_by_id=chief_accountant_user.id,
        request_reason='Needs to post AP bills for the Purchases area.', status='pending',
    )
    req.set_requested_permissions({'chart_of_accounts': True, 'accounts_payable': True})
    db_session.add(req)
    db_session.commit()
    return req


def test_ca_cannot_review(client, db_session, chief_accountant_user, pending_request, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/permission-requests/{pending_request.id}/review', follow_redirects=False)
    assert resp.status_code == 302


def test_admin_approve_merges_permissions_without_touching_others(client, db_session, admin_user,
                                                                    pending_request, limited_accountant,
                                                                    main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post(f'/permission-requests/{pending_request.id}/review', data={
        'action': 'approve', 'review_notes': 'looks fine',
    }, follow_redirects=False)
    assert resp.status_code == 302

    refreshed_target = db.session.get(type(limited_accountant), limited_accountant.id)
    perms = refreshed_target.get_book_permissions()
    assert perms['vendors'] is True          # pre-existing key untouched
    assert perms['chart_of_accounts'] is True  # newly granted
    assert perms['accounts_payable'] is True   # newly granted

    refreshed_req = db.session.get(PermissionChangeRequest, pending_request.id)
    assert refreshed_req.status == 'approved'
    assert refreshed_req.reviewed_by_id == admin_user.id


def test_admin_approve_creates_two_notifications(client, db_session, admin_user, pending_request,
                                                    chief_accountant_user, limited_accountant, main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post(f'/permission-requests/{pending_request.id}/review', data={
        'action': 'approve', 'review_notes': '',
    }, follow_redirects=False)

    requester_notif = Notification.query.filter_by(
        user_id=chief_accountant_user.id, category='success',
        related_type='permission_change_request', related_id=pending_request.id,
    ).first()
    target_notif = Notification.query.filter_by(
        user_id=limited_accountant.id, category='success',
        related_type='permission_change_request', related_id=pending_request.id,
    ).first()
    assert requester_notif is not None
    assert target_notif is not None


def test_admin_reject_makes_no_permission_change(client, db_session, admin_user, pending_request,
                                                    limited_accountant, main_branch):
    original_perms = dict(limited_accountant.get_book_permissions())
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post(f'/permission-requests/{pending_request.id}/review', data={
        'action': 'reject', 'review_notes': 'not needed right now',
    }, follow_redirects=False)

    refreshed_target = db.session.get(type(limited_accountant), limited_accountant.id)
    assert refreshed_target.get_book_permissions() == original_perms

    refreshed_req = db.session.get(PermissionChangeRequest, pending_request.id)
    assert refreshed_req.status == 'rejected'


def test_reject_logs_reject_action_not_original(client, db_session, admin_user, pending_request, main_branch):
    from app.audit.models import AuditLog
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post(f'/permission-requests/{pending_request.id}/review', data={
        'action': 'reject', 'review_notes': 'no',
    }, follow_redirects=False)
    entry = AuditLog.query.filter_by(
        module='permission_change_request', record_id=pending_request.id
    ).order_by(AuditLog.id.desc()).first()
    assert entry.action == 'reject'


def test_already_reviewed_request_cannot_be_reviewed_again(client, db_session, admin_user,
                                                              pending_request, main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    client.post(f'/permission-requests/{pending_request.id}/review',
                data={'action': 'approve', 'review_notes': ''}, follow_redirects=False)
    resp2 = client.post(f'/permission-requests/{pending_request.id}/review',
                         data={'action': 'reject', 'review_notes': ''}, follow_redirects=True)
    assert resp2.status_code == 200
    refreshed_req = db.session.get(PermissionChangeRequest, pending_request.id)
    assert refreshed_req.status == 'approved'  # unchanged by the second attempt


def test_ca_still_cannot_reach_users_edit_directly(client, db_session, chief_accountant_user, main_branch):
    """Regression guard: this plan adds a NEW path, it must not loosen the existing
    admin-only /users/<id>/edit boundary (project-chief-accountant-authz)."""
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(f'/users/{chief_accountant_user.id}/edit', follow_redirects=False)
    assert resp.status_code == 302
