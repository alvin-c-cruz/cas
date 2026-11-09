"""Accounting periods are the administrator's and the chief accountant's only (plan item 2.2).

Owner, 2 Nov 2026: "admin / chief accountant only; `periods` comes out of the permissions staff can
be granted." The routes were already full-access (`full_access_required`), but `periods` was still a
grantable box, so a staff user with it ticked (Philgen's `alvin`) saw a sidebar link to a page that
turned them away (work order 2026-07-14, the drift half).
"""
import pytest

from app import db
from app.users.module_access import all_permission_keys, can_access_module, default_all_permissions

pytestmark = [pytest.mark.integration]


def test_periods_is_not_grantable():
    assert 'periods' not in all_permission_keys()
    assert 'periods' not in default_all_permissions()


def test_a_staff_user_holding_the_old_tick_does_not_get_it(db_session, staff_user):
    perms = staff_user.get_book_permissions()
    perms['periods'] = True
    staff_user.set_book_permissions(perms)
    db.session.commit()
    assert can_access_module(staff_user, 'periods') is False


def test_admin_and_chief_accountant_keep_it(db_session, admin_user, chief_accountant_user):
    assert can_access_module(admin_user, 'periods') is True
    assert can_access_module(chief_accountant_user, 'periods') is True


def _sidebar_html(client, main_branch, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    return client.get('/profile').get_data(as_text=True)


def test_the_staff_sidebar_has_no_periods_link(client, db_session, staff_user, main_branch):
    perms = staff_user.get_book_permissions()
    perms['periods'] = True
    staff_user.set_book_permissions(perms)
    staff_user.set_branches([main_branch])
    db.session.commit()
    assert 'href="/periods"' not in _sidebar_html(client, main_branch, 'staff', 'staff123')


def test_the_chief_accountants_sidebar_has_it(client, db_session, chief_accountant_user, main_branch):
    assert 'href="/periods"' in _sidebar_html(client, main_branch, 'chief', 'chief123')


def test_the_user_form_offers_no_periods_box(client, db_session, admin_user, staff_user, main_branch):
    _sidebar_html(client, main_branch, 'admin', 'admin123')
    html = client.get(f'/users/{staff_user.id}/edit').get_data(as_text=True)
    assert 'name="book_trial_balance"' in html          # the grid is there
    assert 'name="book_periods"' not in html
