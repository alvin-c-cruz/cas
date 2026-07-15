import pytest
from flask import g
from app.permission_requests.models import PermissionChangeRequest

pytestmark = pytest.mark.integration


def _login(client, user):
    # Flask-Login (0.6.3) caches the resolved user on `g._login_user` for the
    # lifetime of the active app context. tests/conftest.py's `app` fixture
    # pushes ONE app context for the whole test function, and the test client
    # reuses it across every client.get() call rather than pushing a fresh one
    # per request -- so `g` (and this cache) survives from request to request
    # within a single test. A test that logs in as one user, makes a request,
    # then logs in as a DIFFERENT user and makes another request needs this
    # explicit pop, or the second request still resolves `current_user` as the
    # first user. Single-login-per-test callers are unaffected (no-op pop).
    g.pop('_login_user', None)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _make_pending_request(db_session, target, requester, reason='need it'):
    req = PermissionChangeRequest(
        target_user_id=target.id, requested_by_id=requester.id,
        request_reason=reason, status='pending',
    )
    req.set_requested_permissions({'chart_of_accounts': True})
    db_session.add(req)
    db_session.commit()
    return req


def test_pending_list_reachable_by_admin_only(client, db_session, admin_user, chief_accountant_user,
                                                accountant_user, main_branch):
    _make_pending_request(db_session, accountant_user, chief_accountant_user)

    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/permission-requests/pending', follow_redirects=False)
    assert resp.status_code == 302  # CA is NOT admin -- excluded, per the SoD boundary

    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/permission-requests/pending')
    assert resp.status_code == 200
    assert b'chief' in resp.data  # requested_by username shown


def test_action_items_badge_includes_pending_permission_requests(client, db_session, admin_user,
                                                                   chief_accountant_user, accountant_user,
                                                                   main_branch):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp_before = client.get('/dashboard')
    count_before = resp_before.data.count(b'action-items') # placeholder presence check

    _make_pending_request(db_session, accountant_user, chief_accountant_user)

    from app.dashboard.action_items_service import count_action_items
    count = count_action_items(admin_user, main_branch.id)
    assert count >= 1
