"""Route-gating + content tests for the single-payslip view."""
from app import db
from app.payroll.models import PayrollRun


class TestPayslipGating:
    def _post_run(self, client, run, login_user, accountant_user, db_session, main_branch):
        login_user(client, 'accountant', 'accountant123')
        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        return db.session.get(PayrollRun, run.id)

    def test_draft_run_blocked(self, client, posted_run_factory, login_user,
                                accountant_user, db_session, main_branch):
        run = posted_run_factory()  # NOT posted -- name is about control-accounts, per its own docstring
        login_user(client, 'accountant', 'accountant123')
        line = run.lines[0]
        resp = client.get(f'/payroll/runs/{run.id}/payslips/{line.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not eligible for payslip printing' in resp.data

    def test_posted_regular_run_allowed(self, client, posted_run_factory, login_user,
                                         accountant_user, db_session, main_branch):
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        line = run2.lines[0]
        resp = client.get(f'/payroll/runs/{run2.id}/payslips/{line.id}')
        assert resp.status_code == 200
        assert line.employee_name.encode() in resp.data

    def test_thirteenth_month_run_blocked(self, client, posted_run_factory, login_user,
                                           accountant_user, db_session, main_branch):
        run = posted_run_factory()
        run.run_type = '13th_month'
        db.session.commit()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        line = run2.lines[0]
        resp = client.get(f'/payroll/runs/{run2.id}/payslips/{line.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not yet available for 13th-month' in resp.data

    def test_staff_blocked(self, client, posted_run_factory, login_user,
                            staff_user, db_session, main_branch):
        run = posted_run_factory()
        # A branch-less staff user gets force-logged-out at login
        # (_post_login_redirect: "No branches available") before ever
        # reaching this route -- assign main_branch first, mirroring every
        # other staff-login test in this suite (test_lifecycle.py's
        # _login_staff helper).
        staff_user.branches.append(main_branch)
        db.session.commit()
        login_user(client, 'staff', 'staff123')
        line = run.lines[0]
        resp = client.get(f'/payroll/runs/{run.id}/payslips/{line.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Only Accountants and Administrators' in resp.data

    def test_print_form_hidden_blocks_route(self, client, posted_run_factory, login_user,
                                             accountant_user, db_session, main_branch):
        from app.settings import AppSettings
        AppSettings.set_setting('payslip_print_form', 'hidden', updated_by='test')
        db.session.commit()
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        line = run2.lines[0]
        resp = client.get(f'/payroll/runs/{run2.id}/payslips/{line.id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Payslip printing is not enabled' in resp.data

    def test_ytd_block_present_and_correct(self, client, posted_run_factory, login_user,
                                            accountant_user, db_session, main_branch):
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        line = run2.lines[0]
        resp = client.get(f'/payroll/runs/{run2.id}/payslips/{line.id}')
        assert resp.status_code == 200
        # _payslip_body.html renders this section label ALL-CAPS, matching the
        # EARNINGS/DEDUCTIONS section labels' casing convention (brief's own
        # Step 4 template text vs. Step 1 test text disagreed on case; the
        # template's casing is kept for visual consistency with its siblings).
        assert b'YEAR-TO-DATE' in resp.data
        # single run -> YTD net pay equals this run's own net pay
        assert '{:,.2f}'.format(line.net_pay).encode() in resp.data
