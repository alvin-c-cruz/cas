"""Integration tests for Feature B — add_approved_email stores role + branches,
scoped to the approver's accessible branches with single-branch auto-assign."""
import pytest
from app.users.approved_emails import ApprovedEmail
from app.audit.models import AuditLog
from app.notifications.models import Notification

pytestmark = [pytest.mark.integration]


def _login(client, user, branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def _post_add(client, email, position, branch_ids=None, notes=''):
    data = {'email': email, 'position': position, 'notes': notes}
    if branch_ids is not None:
        data['branch_ids'] = [str(b) for b in branch_ids]
    return client.post('/approved-emails/add', data=data, follow_redirects=False)


# --- admin: stores role + the chosen branches ---------------------------------

def test_admin_add_stores_role_and_branches(client, db_session, admin_user, main_branch, branch_manila):
    _login(client, admin_user, main_branch, 'admin123')
    resp = _post_add(client, 'd1@example.ph', 'staff', [main_branch.id, branch_manila.id])
    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='d1@example.ph').first()
    assert ae is not None
    assert ae.status == 'approved'
    assert ae.role == 'staff'
    assert sorted(ae.get_branch_ids()) == sorted([main_branch.id, branch_manila.id])


def test_admin_add_stores_book_permissions(client, db_session, admin_user, main_branch):
    """Admin can set the permission grid on the approved-email form; it persists."""
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.post('/approved-emails/add', data={
        'email': 'perm.admin@example.ph', 'position': 'staff',
        'branch_ids': [str(main_branch.id)],
        'book_accounts_payable': '1',
        'book_general_ledger': '1',
    }, follow_redirects=False)
    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='perm.admin@example.ph').first()
    perms = ae.get_book_permissions()
    assert perms.get('accounts_payable') is True
    assert perms.get('general_ledger') is True
    assert perms.get('payments') is not True  # unchecked → not granted


def test_accountant_add_does_not_store_book_permissions(client, db_session, admin_user,
                                                        accountant_user, main_branch):
    """Admin-only scope: an accountant's request never stamps book_permissions, even
    if book_* fields are forged into the POST (grid is configured later in Staff Mgmt)."""
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = client.post('/approved-emails/add', data={
        'email': 'perm.acct@example.ph', 'position': 'staff',
        'book_accounts_payable': '1',  # forged — must be ignored on the accountant path
    }, follow_redirects=False)
    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='perm.acct@example.ph').first()
    assert ae.get_book_permissions() == {}


def test_admin_add_requires_at_least_one_branch(client, db_session, admin_user, main_branch, branch_manila):
    """Admin with multiple branches must pick >=1 — empty selection re-renders, no row."""
    _login(client, admin_user, main_branch, 'admin123')
    resp = _post_add(client, 'd_none@example.ph', 'staff', branch_ids=[])
    assert resp.status_code == 200
    assert ApprovedEmail.query.filter_by(email='d_none@example.ph').first() is None


# --- accountant: scoped to their assigned branches ----------------------------

def test_accountant_cannot_assign_unassigned_branch(client, db_session, admin_user,
                                                     accountant_user, main_branch, branch_manila):
    """An out-of-scope branch id is not an allowed choice → form rejects, no row created."""
    from app.branches.models import Branch
    third = Branch(code='CEB', name='Cebu Branch', is_active=True)
    db_session.add(third)
    db_session.commit()
    accountant_user.set_branches([main_branch, branch_manila])
    db_session.commit()

    _login(client, accountant_user, main_branch, 'accountant123')
    resp = _post_add(client, 'foreign@example.ph', 'viewer', [main_branch.id, third.id])
    assert resp.status_code == 200
    assert ApprovedEmail.query.filter_by(email='foreign@example.ph').first() is None


def test_accountant_single_branch_auto_assigns(client, db_session, admin_user,
                                               accountant_user, main_branch):
    """A single-branch accountant need not pick — their branch is auto-assigned."""
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = _post_add(client, 'auto@example.ph', 'staff', branch_ids=None)  # no branch_ids posted
    assert resp.status_code == 302

    ae = ApprovedEmail.query.filter_by(email='auto@example.ph').first()
    assert ae is not None
    assert ae.status == 'pending'
    assert ae.role == 'staff'
    assert ae.get_branch_ids() == [main_branch.id]


# --- audit + notification carry the role -------------------------------------

def test_accountant_submit_audit_and_notification_name_role(client, db_session, admin_user,
                                                            accountant_user, main_branch):
    _login(client, accountant_user, main_branch, 'accountant123')
    _post_add(client, 'rich@example.ph', 'staff', branch_ids=None)

    ae = ApprovedEmail.query.filter_by(email='rich@example.ph').first()
    audit = AuditLog.query.filter_by(module='approved_email', action='request', record_id=ae.id).first()
    assert audit is not None
    assert 'staff' in (audit.notes or '').lower()

    notif = Notification.query.filter_by(user_id=admin_user.id, related_type='approved_email',
                                         related_id=ae.id).first()
    assert notif is not None
    assert 'staff' in notif.message.lower()


# --- template render paths ----------------------------------------------------

def test_multi_branch_form_renders_branch_picker(client, db_session, admin_user,
                                                 main_branch, branch_manila):
    """With >1 accessible branch, the form shows the multiselect (both branch names)."""
    _login(client, admin_user, main_branch, 'admin123')
    resp = client.get('/approved-emails/add')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert main_branch.name in body and branch_manila.name in body
    assert 'name="branch_ids"' in body


def test_single_branch_form_hides_branch_field(client, db_session, accountant_user, main_branch):
    """With exactly one accessible branch the Branch Assignment field is hidden
    entirely — there is nothing to choose, the branch is auto-assigned server-side."""
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = client.get('/approved-emails/add')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'name="branch_ids"' not in body
    assert 'Branch Assignment' not in body
    assert 'Auto-assigned' not in body


def test_list_shows_position_and_no_branch_column(client, db_session, admin_user, main_branch):
    """Position is shown; the Branch(es) column was removed from the list."""
    ae = ApprovedEmail(email='listed@example.ph', status='approved', role='staff')
    ae.branches = [main_branch]
    db_session.add(ae)
    db_session.commit()

    _login(client, admin_user, main_branch, 'admin123')
    resp = client.get('/approved-emails')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Staff' in body
    assert 'Branch(es)' not in body  # column header removed from both tables


def test_list_combined_status_column(client, db_session, admin_user, main_branch):
    """The two status columns are merged into one: approved-unused -> Available,
    approved-used -> Used, and the old 'Registration Status' header is gone."""
    avail = ApprovedEmail(email='avail@example.ph', status='approved', role='viewer')
    used = ApprovedEmail(email='used@example.ph', status='approved', role='viewer',
                         is_used=True, used_by_user_id=admin_user.id)
    db_session.add_all([avail, used])
    db_session.commit()

    _login(client, admin_user, main_branch, 'admin123')
    resp = client.get('/approved-emails')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert '>Available</span>' in body
    assert '>Used</span>' in body
    assert 'Registration Status' not in body  # merged into the single Status column
