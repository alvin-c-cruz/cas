"""
B-01: "Select all" master checkbox for the Access Permissions grid.

Verifies that id="book_select_all" is present on:
  - /users/<id>/edit  (admin editing a staff user)
  - /staff-management/<id>/edit  (accountant editing a staff user in shared branch)

JS behaviour (indeterminate sync, toggle-all) is client-side only — manual check required.
Manual check notes:
  1. Open /users/<id>/edit for a staff user; confirm "Select all" checkbox appears above the grid.
  2. Check a subset → master goes indeterminate.
  3. Click master → all checked; click again → all unchecked.
  4. Switch role to admin → section hidden; switch back → master syncs.
  5. Repeat on /staff-management/<id>/edit as an accountant with delegatable modules.
"""
import pytest
from app.users.models import User
from app.users.module_access import default_all_permissions

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_user_edit_form_has_select_all_checkbox(client, db_session, admin_user, staff_user, main_branch):
    """Admin editing a staff user sees the 'Select all' master checkbox."""
    # staff_user needs a branch so the before_request gate resolves cleanly for the admin session
    staff_user.set_branches([main_branch])
    db_session.commit()

    _login(client, 'admin', 'admin123')
    resp = client.get(f'/users/{staff_user.id}/edit')
    assert resp.status_code == 200
    assert b'id="book_select_all"' in resp.data


def test_staff_management_edit_has_select_all_checkbox(client, db_session, admin_user,
                                                        accountant_user, main_branch):
    """Accountant editing an in-scope staff member sees the 'Select all' master checkbox."""
    # Give accountant a full permission set so editable_mods is non-empty
    accountant_user.set_book_permissions(default_all_permissions())

    # Create a staff user assigned to the same branch as the accountant
    target = User(username='b01_staff', email='b01_staff@t.com',
                  full_name='B01 Staff', role='staff', is_active=True)
    target.set_password('x')
    db_session.add(target)
    db_session.flush()
    target.set_branches([main_branch])
    db_session.commit()

    _login(client, 'accountant', 'accountant123')
    resp = client.get(f'/staff-management/{target.id}/edit')
    assert resp.status_code == 200
    assert b'id="book_select_all"' in resp.data
