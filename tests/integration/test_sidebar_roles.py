import pytest
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


class TestReceiptLinks:
    def test_collections_link_present(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'Collections' in resp.data

    def test_payments_link_present(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'Payments' in resp.data

    def test_receipts_and_payments_single_link_gone(self, client, db_session,
                                                     admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = client.get('/under-development')
        assert b'Receipts &amp; Payments' not in resp.data
        assert b'Receipts & Payments' not in resp.data
