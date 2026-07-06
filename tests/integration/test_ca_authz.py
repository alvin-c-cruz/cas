"""Authorization boundary tests for the Chief Accountant (CA) role.

Boundary under test (SI-P-72): CA == "admin minus the Admin panel".
- Admin-only (is_admin): company settings, user CRUD, branches, backup, error logs.
- CA-allowed (has_full_access): periods, opening-balance finalize, tax maintenance,
  audit-log view, approved-email management.

Enforcement is consolidated onto two canonical decorators:
  app.utils.authz.admin_panel_required  (is_admin)
  app.utils.authz.full_access_required  (has_full_access)
plus a per-approver role ceiling on the approved-email escalation path.
"""
import pytest

from app import db
from app.users.models import User
from app.users.approved_emails import ApprovedEmail

pytestmark = [pytest.mark.integration, pytest.mark.security]

ADD_URL = '/approved-emails/add'


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _admin_ca_role_count():
    return ApprovedEmail.query.filter(
        ApprovedEmail.role.in_(['admin', 'chief_accountant'])).count()


# ---------------------------------------------------------------------------
# Task 5 — predicate set-assert
# ---------------------------------------------------------------------------

def test_full_access_predicate_set(db_session, admin_user, chief_accountant_user,
                                   accountant_user, staff_user, viewer_user):
    assert admin_user.has_full_access is True
    assert chief_accountant_user.has_full_access is True
    assert accountant_user.has_full_access is False
    assert staff_user.has_full_access is False
    assert viewer_user.has_full_access is False
    # is_admin is the narrower Admin-panel predicate
    assert admin_user.is_admin is True
    assert chief_accountant_user.is_admin is False


# ---------------------------------------------------------------------------
# Task 1 — escalation guard (load-bearing). An approver may never grant a role
# above their own level, and 'admin' is never assignable to anyone. The denied
# combinations below must NOT create any admin/chief_accountant approved-email
# row. Asserted at the DATA layer, not via flash text.
#
# NOTE on scope vs. spec wording: CA (level 4) legitimately MAY assign
# chief_accountant (a same-level, non-escalating grant) — see the separate
# allowed test below. So the denied matrix here is exactly the genuinely
# escalating combos: accountant->{chief_accountant,admin} and CA->admin.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('approver_fx,position', [
    ('accountant_user', 'chief_accountant'),  # accountant cannot escalate to CA
    ('accountant_user', 'admin'),             # accountant cannot escalate to admin
    ('chief_accountant_user', 'admin'),       # CA cannot create an admin
])
def test_escalation_blocked_at_data_layer(request, client, db_session, main_branch,
                                          approver_fx, position):
    approver = request.getfixturevalue(approver_fx)
    _login(client, approver)
    _select_branch(client, main_branch.id)
    email = f'escalate-{approver_fx}-{position}@test.com'
    client.post(ADD_URL, data={'email': email, 'position': position, 'notes': ''},
                follow_redirects=False)
    # No privileged approved-email row was created — the ceiling held.
    assert _admin_ca_role_count() == 0
    assert ApprovedEmail.query.filter_by(email=email).first() is None


# ---------------------------------------------------------------------------
# Task 2 — CA can add + approve, and its own ceiling is chief_accountant.
# ---------------------------------------------------------------------------

def test_ca_add_accountant_is_immediately_approved_with_full_keys(
        client, db_session, chief_accountant_user, main_branch):
    from app.users.module_access import all_permission_keys
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    client.post(ADD_URL, data={'email': 'newacct@test.com',
                               'position': 'accountant', 'notes': ''},
                follow_redirects=False)
    ae = ApprovedEmail.query.filter_by(email='newacct@test.com').first()
    assert ae is not None
    assert ae.role == 'accountant'
    assert ae.status == 'approved'  # CA path == admin path (immediate approve)
    # CA gets the FULL permission-key set as editable (not the accountant subset).
    assert set(ae.get_book_permissions().keys()) == set(all_permission_keys())


def test_ca_may_assign_chief_accountant(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    client.post(ADD_URL, data={'email': 'newca@test.com',
                               'position': 'chief_accountant', 'notes': ''},
                follow_redirects=False)
    ae = ApprovedEmail.query.filter_by(email='newca@test.com').first()
    assert ae is not None
    assert ae.role == 'chief_accountant'
    assert ae.status == 'approved'


def test_ca_can_approve_pending_accountant_request(
        client, db_session, chief_accountant_user, accountant_user, main_branch):
    ae = ApprovedEmail(email='pending@test.com', status='pending', role='accountant',
                       requested_by_user_id=accountant_user.id)
    ae.branches = [main_branch]
    db.session.add(ae)
    db.session.commit()
    ae_id = ae.id
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post(f'/approved-emails/{ae_id}/approve', follow_redirects=False)
    assert resp.status_code == 302
    refreshed = db.session.get(ApprovedEmail, ae_id)
    assert refreshed.status == 'approved'


# ---------------------------------------------------------------------------
# Task 3 — boundary. CA is blocked from every Admin-panel area (302/redirect),
# and reaches every full-access area.
# ---------------------------------------------------------------------------

_ADMIN_PANEL_GET = pytest.mark.parametrize('path', [
    '/settings',            # company_settings edit
    '/settings/modules',    # module catalog
    '/branches',            # branches list
    '/branches/create',     # branch create form
    '/users',               # user CRUD list
    '/backup',              # backup/restore
    '/admin/errors',        # error logs
])


@_ADMIN_PANEL_GET
def test_ca_blocked_from_admin_panel(client, db_session, chief_accountant_user, main_branch, path):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 302, f'CA should be refused at {path}, got {resp.status_code}'


@_ADMIN_PANEL_GET
def test_admin_reaches_admin_panel(client, db_session, admin_user, main_branch, path):
    """Positive control so the CA-denied assertions are non-vacuous."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 200, f'admin should reach {path}, got {resp.status_code}'


def test_ca_blocked_from_branch_create_post(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/branches/create', data={'code': 'NEW', 'name': 'New Branch'},
                       follow_redirects=False)
    assert resp.status_code == 302
    from app.branches.models import Branch
    assert Branch.query.filter_by(code='NEW').first() is None  # nothing created


def test_ca_blocked_from_company_settings_post(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/settings', data={'company_name': 'HACKED'}, follow_redirects=False)
    assert resp.status_code == 302
    from app.settings import AppSettings
    assert AppSettings.get_setting('company_name') != 'HACKED'


def test_ca_allowed_periods(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/periods', follow_redirects=False)
    assert resp.status_code == 200


def test_ca_allowed_vat_categories(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/vat-categories/', follow_redirects=False)
    assert resp.status_code == 200


def test_ca_allowed_audit_log(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/audit-log', follow_redirects=False)
    assert resp.status_code == 200


def test_ca_allowed_approved_emails_add(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get(ADD_URL, follow_redirects=False)
    assert resp.status_code == 200


def test_ca_allowed_opening_balance_finalize_reaches_view(
        client, db_session, chief_accountant_user, main_branch):
    """CA passes the full-access gate on finalize (POST-only). Without a posted
    entry the view body complains it isn't posted yet — proving CA got INTO the
    view rather than being refused by the role gate."""
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/opening-balances/finalize', follow_redirects=True)
    assert b'Only administrators and Chief Accountants can access this area' not in resp.data
    assert b'Post the opening balances before finalizing' in resp.data


# ---------------------------------------------------------------------------
# Task 4 — down-leak. A full-access-only route denies a plain accountant.
# ---------------------------------------------------------------------------

def test_accountant_denied_periods(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/periods', follow_redirects=False)
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Task 6 — CA cannot change its own role (route-level: /users is admin-only).
# ---------------------------------------------------------------------------

def test_ca_cannot_change_own_role(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post(f'/users/{chief_accountant_user.id}/edit', data={
        'username': 'chief', 'email': 'chief@test.com',
        'full_name': 'Chief Accountant', 'role': 'admin', 'is_active': 'y',
    }, follow_redirects=False)
    assert resp.status_code == 302  # admin_panel_required refuses CA at /users
    refreshed = db.session.get(User, chief_accountant_user.id)
    assert refreshed.role == 'chief_accountant'


# ---------------------------------------------------------------------------
# Task 7 — SI save_print_layout: CA allowed (accounting-doc config); accountant
# and staff forbidden (403).
# ---------------------------------------------------------------------------

def test_ca_can_save_print_layout(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-invoices/print-layout', json={})
    assert resp.status_code == 200


def test_accountant_forbidden_from_save_print_layout(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-invoices/print-layout', json={})
    assert resp.status_code == 403


def test_staff_forbidden_from_save_print_layout(client, db_session, staff_user, main_branch):
    staff_user.set_branches([main_branch])
    db.session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/sales-invoices/print-layout', json={})
    assert resp.status_code == 403
