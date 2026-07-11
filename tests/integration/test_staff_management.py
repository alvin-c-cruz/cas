import pytest
from app import db
from app.users.models import User
from app.branches.models import Branch
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, username, password='accountant123'):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _staff(db_session, code_branch, role='staff', perms=None, username='s1'):
    u = User(username=username, email=f'{username}@t.com', full_name='S', role=role, is_active=True)
    u.set_password('x')
    if perms is not None:
        u.set_book_permissions(perms)
    db_session.add(u); db_session.flush()
    u.set_branches([code_branch])
    db_session.commit()
    return u


def test_non_accountant_blocked(client, db_session, admin_user, staff_user, main_branch):
    _login(client, 'staff', 'staff123')
    resp = client.get('/staff-management', follow_redirects=True)
    assert resp.request.path != '/staff-management'   # redirected away


def test_admin_blocked_uses_own_page(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    resp = client.get('/staff-management', follow_redirects=True)
    assert resp.request.path != '/staff-management'


def test_list_shows_only_shared_branch_staff(client, db_session, admin_user, accountant_user,
                                              main_branch, branch_manila):
    shares = _staff(db_session, main_branch, username='shares')
    outsider = _staff(db_session, branch_manila, username='outsider')
    _login(client, 'accountant')
    resp = client.get('/staff-management')
    assert resp.status_code == 200
    assert b'shares' in resp.data
    assert b'outsider' not in resp.data


def test_no_create_route(client, db_session, admin_user, accountant_user, main_branch):
    _login(client, 'accountant')
    resp = client.get('/staff-management/create')
    assert resp.status_code == 404


def test_edit_out_of_scope_forbidden(client, db_session, admin_user, accountant_user,
                                     main_branch, branch_manila):
    other = _staff(db_session, branch_manila, username='foreign')
    _login(client, 'accountant')
    resp = client.get(f'/staff-management/{other.id}/edit')
    assert resp.status_code == 403


def test_edit_grants_subset_and_preserves_out_of_scope(client, db_session, admin_user,
                                                       accountant_user, main_branch):
    # accountant holds only accounts_payable + payments (narrow the backfilled set)
    accountant_user.set_book_permissions({'accounts_payable': True, 'payments': True})
    target = _staff(db_session, main_branch, perms={'general_ledger': True}, username='tgt')
    db_session.commit()
    _login(client, 'accountant')
    resp = client.post(f'/staff-management/{target.id}/edit', data={
        'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
        'book_accounts_payable': '1',
        'book_general_ledger': '1',     # forged: accountant doesn't hold GL → ignored, but preserved from existing
    }, follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db_session.get(User, target.id)
    perms = refreshed.get_book_permissions()
    assert perms.get('accounts_payable') is True     # granted (in accountant's set)
    assert perms.get('payments') is not True          # accountant has it but didn't grant
    assert perms.get('general_ledger') is True        # preserved (outside accountant's set)
    # audit row exists
    assert db.session.execute(
        db.select(AuditLog).filter_by(module='user', record_id=target.id)
    ).scalars().first() is not None


def test_edit_cannot_promote_to_accountant(client, db_session, admin_user, accountant_user, main_branch):
    target = _staff(db_session, main_branch, username='noprom')
    _login(client, 'accountant')
    resp = client.post(f'/staff-management/{target.id}/edit', data={
        'role': 'accountant', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
    }, follow_redirects=True)
    refreshed = db_session.get(User, target.id)
    assert refreshed.role in ('staff', 'viewer')      # forged accountant rejected by form choices


def test_toggle_active_flips_and_audits(client, db_session, admin_user, accountant_user,
                                        main_branch):
    target = _staff(db_session, main_branch, username='toggler')
    assert target.is_active is True
    _login(client, 'accountant')
    resp = client.post(f'/staff-management/{target.id}/toggle-active',
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.expire(target)
    assert target.is_active is False
    # audit row logged for the toggle
    row = db.session.execute(
        db.select(AuditLog).filter_by(module='user', record_id=target.id,
                                      action='status_changed')
    ).scalars().first()
    assert row is not None


def test_toggle_active_out_of_scope_forbidden(client, db_session, admin_user, accountant_user,
                                              main_branch, branch_manila):
    outsider = _staff(db_session, branch_manila, username='outcast')
    _login(client, 'accountant')
    resp = client.post(f'/staff-management/{outsider.id}/toggle-active',
                       follow_redirects=False)
    assert resp.status_code == 403


def test_chief_accountant_can_reach_editor(client, db_session, admin_user,
                                           chief_accountant_user, main_branch):
    """A Chief Accountant may use the Staff Management editor. BUG-CA-CANNOT-EDIT."""
    target = _staff(db_session, main_branch, username='catgt')
    _login(client, 'chief', 'chief123')
    resp = client.get(f'/staff-management/{target.id}/edit')
    assert resp.status_code == 200


def test_chief_accountant_can_grant_optional_module(client, db_session, admin_user,
                                                    chief_accountant_user, main_branch):
    """A CA's grantable ceiling is the whole grid, so they can grant Sales Orders."""
    target = _staff(db_session, main_branch, username='cagr')
    _login(client, 'chief', 'chief123')
    resp = client.post(f'/staff-management/{target.id}/edit', data={
        'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
        'book_sales_orders': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert db_session.get(User, target.id).get_book_permissions().get('sales_orders') is True


def test_chief_accountant_cannot_edit_accountant(client, db_session, admin_user,
                                                 chief_accountant_user, accountant_user, main_branch):
    """Staff Management scope stays staff/viewer only -- editing an accountant is
    still 403 (an accountant's perms remain admin-only via /users/edit)."""
    _login(client, 'chief', 'chief123')
    resp = client.get(f'/staff-management/{accountant_user.id}/edit')
    assert resp.status_code == 403


def test_chief_accountant_grid_renders_optional_modules(client, db_session, admin_user,
                                                        chief_accountant_user, main_branch):
    """BUG-STAFFMGMT-GRID-OMITS-OPTIONAL: the CA editor must RENDER the per_user
    optional Sales-area checkboxes (Sales Orders / Delivery Receipts / Quotations),
    not just honor them on save -- a human CA can only grant what the grid shows."""
    target = _staff(db_session, main_branch, username='gridtgt')
    _login(client, 'chief', 'chief123')
    resp = client.get(f'/staff-management/{target.id}/edit')
    assert resp.status_code == 200
    assert b'name="book_sales_orders"' in resp.data
    assert b'name="book_delivery_receipts"' in resp.data
    assert b'name="book_quotations"' in resp.data


def test_accountant_grid_hides_unheld_optional(client, db_session, admin_user,
                                               accountant_user, main_branch):
    """The grid ceiling is still own_keys: a plain accountant who does NOT hold
    Quotations must not see book_quotations (guards against over-exposure), while
    a module they DO hold is shown."""
    accountant_user.set_book_permissions({'accounts_payable': True})
    target = _staff(db_session, main_branch, username='scopetgt')
    db_session.commit()
    _login(client, 'accountant')
    resp = client.get(f'/staff-management/{target.id}/edit')
    assert resp.status_code == 200
    assert b'name="book_accounts_payable"' in resp.data   # held -> shown
    assert b'name="book_quotations"' not in resp.data      # not held -> hidden
