"""Sidebar gate for Staff Management must match the route's own guard.

BUG-CA-STAFF-MANAGEMENT-NO-NAV-LINK: staff_management's `accountant_required`
admits ('accountant', 'chief_accountant'), but base.html rendered the nav block
only for role == 'accountant'. A chief accountant was therefore fully authorised
server-side and could never reach the page by clicking. Found twice by /ui-test
on RIC (2026-08-04, re-confirmed 2026-08-05), where there is no plain accountant
at all, so the page was unreachable for every user.

Asserts the full href ATTRIBUTE, never the label: the section heading is also the
text "Staff Management", so `b'Staff Management' in resp.data` passes even when
the link is absent -- it would have passed on the broken code.

Note admin is deliberately EXCLUDED: accountant_required does not admit admin, so
showing admin the link would create a control that flashes and redirects.
"""
import pytest

from app import db

pytestmark = [pytest.mark.users, pytest.mark.integration]

STAFF_HREF = b'href="/staff-management"'
EMAILS_HREF = b'href="/approved-emails"'


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestStaffManagementNavGate:

    def test_chief_accountant_SEES_the_staff_management_link(
            self, client, db_session, chief_accountant_user, main_branch):
        """The bug. The CA is authorised by accountant_required and must be able
        to click through, not just reach the URL by knowing it."""
        chief_accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, chief_accountant_user.username, 'chief123')
        resp = client.get('/under-development')
        assert STAFF_HREF in resp.data

    def test_accountant_still_sees_it(self, client, db_session,
                                      accountant_user, main_branch):
        """Unchanged behaviour -- the fix widens, it must not move."""
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert STAFF_HREF in resp.data

    def test_admin_does_NOT_see_it(self, client, db_session, admin_user, main_branch):
        """accountant_required admits ('accountant','chief_accountant') only, so a
        link for admin would flash 'not permitted' and redirect -- a dead control."""
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert STAFF_HREF not in resp.data

    def test_staff_does_NOT_see_it(self, client, db_session, staff_user, main_branch):
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/under-development')
        assert STAFF_HREF not in resp.data

    def test_chief_accountant_gets_exactly_ONE_approved_emails_link(
            self, client, db_session, chief_accountant_user, main_branch):
        """Guards the obvious wrong fix. The accountant-only block wraps BOTH
        Staff Management and Approved Emails, and a CA already reaches Approved
        Emails through the has_full_access block. Widening the whole block would
        hand the CA a duplicate nav entry."""
        chief_accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, chief_accountant_user.username, 'chief123')
        resp = client.get('/under-development')
        assert resp.data.count(EMAILS_HREF) == 1, (
            'CA should have exactly one Approved Emails link, got %d'
            % resp.data.count(EMAILS_HREF))

    def test_accountant_keeps_its_approved_emails_link(
            self, client, db_session, accountant_user, main_branch):
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert EMAILS_HREF in resp.data


def test_nav_gate_matches_the_route_guard():
    """Binds the two role lists that drifted apart, so they cannot drift again.

    The bug was a hardcoded role tuple in a decorator disagreeing with a
    hardcoded role test in a template. A render test proves today's behaviour;
    this proves the SOURCE of that behaviour still agrees with the backend.
    """
    import inspect
    import re
    from app.staff_management import views as sm_views

    src = inspect.getsource(sm_views.accountant_required)
    m = re.search(r"role not in \(([^)]*)\)", src)
    assert m, 'could not read the role tuple out of accountant_required'
    guard_roles = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert guard_roles == {'accountant', 'chief_accountant'}, (
        'accountant_required changed to %s -- update the base.html nav gate and '
        'this test together' % sorted(guard_roles))
