import pytest
from app import db

pytestmark = [pytest.mark.users, pytest.mark.integration]


"""Sidebar shows correct links per role."""


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestSidebarRoles:
    def test_admin_sees_user_management(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'User Management' in resp.data

    def test_accountant_does_not_see_user_management(self, client, db_session,
                                                      admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert b'User Management' not in resp.data

    def test_admin_sees_audit_log(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'Audit Log' in resp.data

    def test_accountant_sees_audit_log(self, client, db_session,
                                       admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert b'Audit Log' in resp.data

    def test_staff_does_not_see_admin_section(self, client, db_session,
                                              admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/under-development')
        assert b'User Management' not in resp.data
        assert b'Audit Log' not in resp.data

    def test_viewer_does_not_see_admin_section(self, client, db_session,
                                               admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/under-development')
        assert b'User Management' not in resp.data
        assert b'Audit Log' not in resp.data


class TestGeneralLedgerNavLink:
    """GL changed from a nav-item--soon stub to a real can_access_module-gated link."""

    def test_admin_sees_gl_link(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'/reports/general-ledger' in resp.data

    def test_accountant_sees_gl_link(self, client, db_session, admin_user,
                                      accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert b'/reports/general-ledger' in resp.data

    def test_viewer_sees_gl_link(self, client, db_session, admin_user,
                                  viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/under-development')
        assert b'/reports/general-ledger' in resp.data

    def test_staff_without_grant_does_not_see_gl_link(self, client, db_session,
                                                        admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        # Remove general_ledger from staff's book_permissions (it's absent by default,
        # but be explicit to guard against future conftest changes).
        perms = staff_user.get_book_permissions()
        perms.pop('general_ledger', None)
        staff_user.set_book_permissions(perms)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/under-development')
        assert b'/reports/general-ledger' not in resp.data

    def test_gl_link_is_not_a_soon_stub(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        html = resp.data.decode()
        # The Soon badge and the under-development URL must no longer appear for GL.
        assert 'feature=General+Ledger' not in html
        assert 'feature=General%20Ledger' not in html


class TestChiefAccountantApprovedEmails:
    """A Chief Accountant manages staff registrations but is NOT a sysadmin, so the
    'Approved Emails' page must be reachable from her sidebar (previously the link was
    shown only to admins and to plain accountants, leaving a CA with no menu path)."""

    def test_ca_sees_approved_emails_link(self, client, db_session,
                                          chief_accountant_user, main_branch):
        db_session.commit()
        login(client, 'chief', 'chief123')
        resp = client.get('/under-development')
        assert b'/approved-emails' in resp.data
        assert b'Approved Emails' in resp.data

    def test_ca_SEES_staff_management_link(self, client, db_session,
                                           chief_accountant_user, main_branch):
        # INVERTED 2026-08-05 (BUG-CA-STAFF-MANAGEMENT-NO-NAV-LINK). This test used to
        # assert the opposite, on the stated grounds that "staff_management is
        # accountant-only; a CA must not get a dead link to it". That premise is wrong:
        # app/staff_management/views.py::accountant_required admits
        # ('accountant', 'chief_accountant'), and a CA request returns HTTP 200 with the
        # real page -- verified live on RIC data. The link was never dead; the CA simply
        # had no way to click it. Codifying the wrong premise here is very likely why the
        # gap survived: the suite asserted the defect was correct behaviour.
        #
        # The "no dead link" principle it was reaching for is preserved and now applied
        # where it actually holds -- see test_admin_does_NOT_see_it in
        # test_sidebar_staff_management_gate.py: accountant_required rejects ADMIN, so an
        # admin link really would flash-and-redirect.
        #
        # data-section="staff" stays absent for a CA on purpose: the CA's copy of the link
        # lives inside the existing Tax & Oversight section (where she already has Audit
        # Log, Control Accounts and Approved Emails), not in a second accountant-style
        # section that would duplicate all three.
        db_session.commit()
        login(client, 'chief', 'chief123')
        resp = client.get('/under-development')
        assert b'href="/staff-management"' in resp.data
        assert b'data-section="staff"' not in resp.data

    def test_accountant_still_sees_approved_emails_link(self, client, db_session,
                                                        admin_user, accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/under-development')
        assert b'/approved-emails' in resp.data

    def test_staff_does_not_see_approved_emails_link(self, client, db_session,
                                                     admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/under-development')
        assert b'/approved-emails' not in resp.data


class TestReceiptLinks:
    def test_collections_link_present(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        # Sidebar nav label is now "Cash Receipts (Collection)" (was "Collections")
        assert b'Cash Receipts' in resp.data

    def test_payments_link_present(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        # Sidebar nav label is now "Cash Disbursements (Pay Bill)" (was "Payments")
        assert b'Cash Disbursements' in resp.data

    def test_receipts_and_payments_single_link_gone(self, client, db_session,
                                                     admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'Receipts &amp; Payments' not in resp.data
        assert b'Receipts & Payments' not in resp.data
