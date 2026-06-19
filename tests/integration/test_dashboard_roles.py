import pytest
pytestmark = [pytest.mark.users, pytest.mark.integration]


"""Dashboard role-based visibility tests.

Covers: page access, financial metrics (all roles), sidebar nav gating,
topbar New button, and Action Items link per role.
"""


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def get_dashboard(client):
    return client.get('/dashboard')


# ---------------------------------------------------------------------------
# Access — all roles reach /dashboard with 200
# ---------------------------------------------------------------------------

class TestDashboardAccess:
    def test_admin_can_access(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        resp = get_dashboard(client)
        assert resp.status_code == 200

    def test_accountant_can_access(self, client, db_session, admin_user, accountant_user,
                                   main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = get_dashboard(client)
        assert resp.status_code == 200

    def test_staff_can_access(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = get_dashboard(client)
        assert resp.status_code == 200

    def test_viewer_can_access(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = get_dashboard(client)
        assert resp.status_code == 200

    def test_unauthenticated_redirected_to_login(self, client, db_session):
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Financial metrics — visible to ALL roles
# ---------------------------------------------------------------------------

class TestDashboardMetricsAllRoles:
    """Every role sees the same financial dashboard content."""

    def _check_metrics(self, client, username, password, db_session, user, main_branch):
        user.add_branch(main_branch)
        db_session.commit()
        login(client, username, password)
        resp = get_dashboard(client)
        html = resp.data
        assert b'Financial Dashboard' in html
        assert b'Revenue' in html
        assert b'Expenses' in html
        assert b'Accounts Receivable' in html
        assert b'Accounts Payable' in html

    def test_admin_sees_metrics(self, client, db_session, admin_user, main_branch):
        self._check_metrics(client, 'admin', 'admin123', db_session, admin_user, main_branch)

    def test_accountant_sees_metrics(self, client, db_session, admin_user, accountant_user,
                                     main_branch):
        admin_user.add_branch(main_branch)
        self._check_metrics(client, 'accountant', 'accountant123', db_session,
                            accountant_user, main_branch)

    def test_staff_sees_metrics(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        self._check_metrics(client, 'staff', 'staff123', db_session, staff_user, main_branch)

    def test_viewer_sees_metrics(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        self._check_metrics(client, 'viewer', 'viewer123', db_session, viewer_user, main_branch)


# ---------------------------------------------------------------------------
# "+ New" topbar button — visible to admin/accountant/staff; hidden from viewer
# ---------------------------------------------------------------------------

class TestDashboardNewButton:
    # The topbar "+ New" quick-create dropdown was removed in commit 1b8c659
    # (feat(ui): remove the topbar + New quick-create dropdown). The button must
    # now be absent for EVERY role; document creation is reached via the
    # list-page "Enter ..." launch buttons instead.
    def test_admin_no_new_button(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'id="topbarNewBtn"' not in get_dashboard(client).data

    def test_accountant_no_new_button(self, client, db_session, admin_user, accountant_user,
                                      main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'id="topbarNewBtn"' not in get_dashboard(client).data

    def test_staff_no_new_button(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'id="topbarNewBtn"' not in get_dashboard(client).data

    def test_viewer_no_new_button(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        assert b'id="topbarNewBtn"' not in get_dashboard(client).data


# ---------------------------------------------------------------------------
# Action Items sidebar link — visible to admin/accountant/staff; hidden from viewer
# ---------------------------------------------------------------------------

class TestDashboardActionItemsLink:
    def test_admin_sees_action_items(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'Action Items' in get_dashboard(client).data

    def test_accountant_sees_action_items(self, client, db_session, admin_user, accountant_user,
                                          main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'Action Items' in get_dashboard(client).data

    def test_staff_sees_action_items(self, client, db_session, admin_user, staff_user,
                                     main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'Action Items' in get_dashboard(client).data

    def test_viewer_no_action_items(self, client, db_session, admin_user, viewer_user,
                                    main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        assert b'Action Items' not in get_dashboard(client).data


# ---------------------------------------------------------------------------
# VAT Categories & Withholding Tax maintenance links
# — visible to admin/accountant; hidden from staff/viewer
# (/withholding-tax/ distinguishes the maintenance link from /reports/bir/alphalist)
# ---------------------------------------------------------------------------

class TestDashboardMaintenanceLinks:
    def test_admin_sees_vat_categories(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'VAT Categories' in get_dashboard(client).data

    def test_admin_sees_wht_maintenance_link(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'/withholding-tax/' in get_dashboard(client).data

    def test_accountant_sees_vat_categories(self, client, db_session, admin_user, accountant_user,
                                            main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'VAT Categories' in get_dashboard(client).data

    def test_staff_no_vat_categories(self, client, db_session, admin_user, staff_user,
                                     main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'VAT Categories' not in get_dashboard(client).data

    def test_staff_no_wht_maintenance_link(self, client, db_session, admin_user, staff_user,
                                           main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'/withholding-tax/' not in get_dashboard(client).data

    def test_viewer_no_vat_categories(self, client, db_session, admin_user, viewer_user,
                                      main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        assert b'VAT Categories' not in get_dashboard(client).data


# ---------------------------------------------------------------------------
# Admin section: Audit Log, User Management, Company Settings, Approved Emails
# ---------------------------------------------------------------------------

class TestDashboardAdminSection:
    def test_admin_sees_audit_log(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'Audit Log' in get_dashboard(client).data

    def test_accountant_sees_audit_log(self, client, db_session, admin_user, accountant_user,
                                       main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'Audit Log' in get_dashboard(client).data

    def test_staff_no_audit_log(self, client, db_session, admin_user, staff_user, main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'Audit Log' not in get_dashboard(client).data

    def test_viewer_no_audit_log(self, client, db_session, admin_user, viewer_user, main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        assert b'Audit Log' not in get_dashboard(client).data

    def test_admin_sees_user_management(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'User Management' in get_dashboard(client).data

    def test_accountant_no_user_management(self, client, db_session, admin_user, accountant_user,
                                           main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'User Management' not in get_dashboard(client).data

    def test_staff_no_user_management(self, client, db_session, admin_user, staff_user,
                                      main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        assert b'User Management' not in get_dashboard(client).data

    def test_admin_sees_company_settings(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'Company Settings' in get_dashboard(client).data

    def test_accountant_no_company_settings(self, client, db_session, admin_user, accountant_user,
                                            main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'Company Settings' not in get_dashboard(client).data

    def test_admin_sees_approved_emails(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'admin', 'admin123')
        assert b'Approved Emails' in get_dashboard(client).data

    def test_accountant_no_approved_emails(self, client, db_session, admin_user, accountant_user,
                                           main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        assert b'Approved Emails' not in get_dashboard(client).data


# ---------------------------------------------------------------------------
# Action Items page content — role-gated at view level
# ---------------------------------------------------------------------------

class TestActionItemsPage:
    """Accountant/admin see drafts + approvals; staff sees drafts only; viewer
    is blocked from the page entirely."""

    def test_accountant_can_access_action_items(self, client, db_session, admin_user,
                                                accountant_user, main_branch):
        admin_user.add_branch(main_branch)
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')
        resp = client.get('/action-items')
        assert resp.status_code == 200

    def test_staff_can_access_action_items(self, client, db_session, admin_user, staff_user,
                                           main_branch):
        admin_user.add_branch(main_branch)
        staff_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'staff', 'staff123')
        resp = client.get('/action-items')
        assert resp.status_code == 200

    def test_viewer_blocked_from_action_items(self, client, db_session, admin_user, viewer_user,
                                              main_branch):
        admin_user.add_branch(main_branch)
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/action-items')
        # Viewers have no action items — the route redirects them away.
        assert resp.status_code == 302
        assert '/action-items' not in resp.headers.get('Location', '')
