"""Regression tests for BUG-EDITUSER-DROPS-OPTIONAL-PERMS.

The admin User Management edit form must persist per-user OPTIONAL modules
(sales_orders / delivery_receipts / quotations / credit_memos / debit_memos),
not silently drop them. The bug: edit_user built book_permissions from
`MODULE_REGISTRY if not m.get('optional')`, which excludes the per_user
optionals; `set_book_permissions` then replaces the whole stored dict, wiping
any prior grant and making a new one unwritable. Fix: iterate
`all_permission_keys()` (`not optional OR per_user`) instead.

Mirrors tests/integration/test_admin_sets_viewer_permissions.py.
Trap: edit_user rejects a changed username/email (re-renders WITHOUT saving),
so every POST sends the target's CURRENT username + email.
"""
import pytest

from app.users.models import User
from app.audit.models import AuditLog
from app.users.module_access import all_permission_keys
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.users]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _edit_payload(main_branch, **overrides):
    """The staff_user's current identity fields + a branch, plus any book_ flags."""
    data = {
        'username': 'staff', 'email': 'staff@test.com', 'full_name': 'Staff User',
        'role': 'staff', 'branch_ids': [str(main_branch.id)], 'is_active': 'y',
    }
    data.update(overrides)
    return data


def test_grant_optional_module_persists(client, db_session, admin_user, staff_user, main_branch):
    """Admin ticks Sales Orders for a staff user -> it must be stored."""
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch, book_sales_orders='1'),
                       follow_redirects=True)
    assert resp.status_code == 200
    perms = db_session.get(User, staff_user.id).get_book_permissions()
    assert perms.get('sales_orders') is True


def test_unrelated_edit_does_not_strip_optional(client, db_session, admin_user, staff_user, main_branch):
    """A user already holding sales_orders keeps it when only the name is edited
    (the grid still submits book_sales_orders=1 reflecting the current state)."""
    staff_user.set_book_permissions({'accounts_payable': True, 'sales_orders': True})
    db_session.commit()
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch, full_name='Renamed Staff',
                                          book_accounts_payable='1', book_sales_orders='1'),
                       follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db_session.get(User, staff_user.id)
    assert refreshed.full_name == 'Renamed Staff'
    assert refreshed.get_book_permissions().get('sales_orders') is True


def test_revoke_optional_module_still_works(client, db_session, admin_user, staff_user, main_branch):
    """Submitting the form with sales_orders UNticked revokes it (no over-correction
    into 'never revoke')."""
    staff_user.set_book_permissions({'sales_orders': True})
    db_session.commit()
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch),  # no book_sales_orders
                       follow_redirects=True)
    assert resp.status_code == 200
    assert db_session.get(User, staff_user.id).get_book_permissions().get('sales_orders') is False


def test_granting_optional_module_is_audited(client, db_session, admin_user, staff_user, main_branch):
    """The permission change must produce an audit row (the diff now spans the
    per_user optionals too)."""
    _login(client, 'admin', 'admin123')
    client.post(f'/users/{staff_user.id}/edit',
                data=_edit_payload(main_branch, book_sales_orders='1'),
                follow_redirects=True)
    row = db.session.execute(
        db.select(AuditLog).filter_by(module='user', record_id=staff_user.id)
    ).scalars().first()
    assert row is not None


def test_edit_grid_renders_every_grantable_key(client, db_session, admin_user, staff_user, main_branch):
    """Grid-completeness pin: every all_permission_keys() key must render a
    checkbox, or the replace-over-all_permission_keys() save would silently
    revoke a key that has no checkbox."""
    _login(client, 'admin', 'admin123')
    resp = client.get(f'/users/{staff_user.id}/edit')
    assert resp.status_code == 200
    for key in all_permission_keys():
        assert f'name="book_{key}"'.encode() in resp.data, f'missing checkbox for {key}'


def test_grant_employees_module_persists(client, db_session, admin_user, staff_user, main_branch):
    """Admin ticks Employees for a staff user -> it must be stored (same shape as sales_orders)."""
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch, book_employees='1'),
                       follow_redirects=True)
    assert resp.status_code == 200
    perms = db_session.get(User, staff_user.id).get_book_permissions()
    assert perms.get('employees') is True


def test_grant_units_of_measure_module_persists(client, db_session, admin_user, staff_user, main_branch):
    """Admin ticks Units of Measure for a staff user -> it must be stored."""
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch, book_units_of_measure='1'),
                       follow_redirects=True)
    assert resp.status_code == 200
    perms = db_session.get(User, staff_user.id).get_book_permissions()
    assert perms.get('units_of_measure') is True


def test_grant_products_module_persists(client, db_session, admin_user, staff_user, main_branch):
    """Admin ticks Products for a staff user -> it must be stored."""
    _login(client, 'admin', 'admin123')
    resp = client.post(f'/users/{staff_user.id}/edit',
                       data=_edit_payload(main_branch, book_products='1'),
                       follow_redirects=True)
    assert resp.status_code == 200
    perms = db_session.get(User, staff_user.id).get_book_permissions()
    assert perms.get('products') is True
