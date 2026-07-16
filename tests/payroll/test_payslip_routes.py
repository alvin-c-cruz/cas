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
        """Builds TWO posted regular runs for the SAME employee in different
        months (mirrors test_ytd_totals.py::test_multiple_runs_sum_correctly's
        multi-run fixture-building pattern) so the current-period net pay and
        the YTD net pay are genuinely different numbers -- a single-run test
        cannot distinguish "template correctly reads ytd.net_pay" from "a bug
        swapped ytd.net_pay for line.net_pay and it happened to look right
        anyway" (both figures are numerically identical with only one run).
        """
        from datetime import date
        from decimal import Decimal
        from app.employees.models import Employee
        from app.payroll.models import PayrollRunLine

        run1 = posted_run_factory(run_number='PR-2026-06-0001')
        run1_posted = self._post_run(client, run1, login_user, accountant_user, db_session, main_branch)
        emp = db.session.get(Employee, run1_posted.lines[0].employee_id)

        run2 = PayrollRun(
            run_number='PR-2026-07-0001', branch_id=main_branch.id, run_type='regular',
            pay_frequency='monthly', period_year=2026, period_month=7, semi_period=0,
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
            pay_date=date(2026, 8, 5), semi_timing='second_cutoff', status='draft',
        )
        db.session.add(run2)
        db.session.flush()
        line2 = PayrollRunLine(
            run_id=run2.id, line_number=1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
            tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run2.lines.append(line2)
        db.session.commit()
        line2.calculate_amounts()
        run2.calculate_totals()
        db.session.commit()

        run2_posted = self._post_run(client, run2, login_user, accountant_user, db_session, main_branch)
        line2_posted = run2_posted.lines[0]

        expected_ytd_net = run1_posted.lines[0].net_pay + line2_posted.net_pay
        # sanity: the two figures the assertions below pin must actually be
        # different, or this test would be just as weak as the one it replaces
        assert expected_ytd_net != line2_posted.net_pay

        resp = client.get(f'/payroll/runs/{run2_posted.id}/payslips/{line2_posted.id}')
        assert resp.status_code == 200
        # _payslip_body.html renders this section label ALL-CAPS, matching the
        # EARNINGS/DEDUCTIONS section labels' casing convention (brief's own
        # Step 4 template text vs. Step 1 test text disagreed on case; the
        # template's casing is kept for visual consistency with its siblings).
        assert b'YEAR-TO-DATE' in resp.data
        # current-period net pay (this run's own line) must be present
        assert '{:,.2f}'.format(line2_posted.net_pay).encode() in resp.data
        # YTD net pay (sum across BOTH posted runs) must also be present, and
        # is genuinely different from the current-period figure above --
        # proving the template is reading ytd.net_pay, not re-echoing
        # line.net_pay a second time in the YTD section
        assert '{:,.2f}'.format(expected_ytd_net).encode() in resp.data


class TestPayslipLinkMirrorsRouteGate:
    """detail.html's "Payslip" link must mirror the FULL route gate enforced
    by _payslip_gate_or_redirect (payslip_print_form/payslip_print_access,
    on top of the run_type/status check the link already had) -- otherwise a
    posted regular run with payslip_print_form='hidden' still shows a link
    that redirects with a flash the moment it's clicked. Mirrors how
    sales_invoices/templates/sales_invoices/detail.html conditions its own
    print link on sv_print_form/sv_print_access."""

    def _post_run(self, client, run, login_user, accountant_user, db_session, main_branch):
        login_user(client, 'accountant', 'accountant123')
        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        return db.session.get(PayrollRun, run.id)

    def test_link_hidden_when_print_form_hidden(self, client, posted_run_factory, login_user,
                                                  accountant_user, db_session, main_branch):
        from app.settings import AppSettings
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        AppSettings.set_setting('payslip_print_form', 'hidden', updated_by='test')
        db.session.commit()

        resp = client.get(f'/payroll/runs/{run2.id}')
        assert resp.status_code == 200
        assert b'>Payslip</a>' not in resp.data

    def test_link_shown_for_posted_regular_run_by_default(self, client, posted_run_factory, login_user,
                                                            accountant_user, db_session, main_branch):
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)

        resp = client.get(f'/payroll/runs/{run2.id}')
        assert resp.status_code == 200
        assert b'>Payslip</a>' in resp.data


class TestPayslipPrintAll:
    def _post_run(self, client, run, login_user, accountant_user, db_session, main_branch):
        login_user(client, 'accountant', 'accountant123')
        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        return db.session.get(PayrollRun, run.id)

    def test_print_all_shows_every_line(self, client, posted_run_factory, login_user,
                                         accountant_user, db_session, main_branch):
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        resp = client.get(f'/payroll/runs/{run2.id}/payslips')
        assert resp.status_code == 200
        for line in run2.lines:
            assert line.employee_name.encode() in resp.data

    def test_print_all_respects_same_gate_as_single(self, client, posted_run_factory,
                                                      login_user, accountant_user,
                                                      db_session, main_branch):
        run = posted_run_factory()  # draft
        login_user(client, 'accountant', 'accountant123')
        resp = client.get(f'/payroll/runs/{run.id}/payslips', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not eligible for payslip printing' in resp.data

    def test_print_all_button_shown_for_posted_regular_run_by_default(
            self, client, posted_run_factory, login_user, accountant_user,
            db_session, main_branch):
        """detail.html's "Print All Payslips" button must itself read
        payslip_link_visible correctly -- TestPayslipLinkMirrorsRouteGate's
        two tests only prove the SHARED {% set %} variable's truth value via
        the per-line "Payslip" link; they cannot catch a mutation isolated to
        the button's own {% if %} (e.g. a typo'd variable name at that one
        spot). This test exercises the button's own conditional directly."""
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)

        resp = client.get(f'/payroll/runs/{run2.id}')
        assert resp.status_code == 200
        assert b'Print All Payslips' in resp.data

    def test_print_all_button_hidden_when_print_form_hidden(
            self, client, posted_run_factory, login_user, accountant_user,
            db_session, main_branch):
        """Negative counterpart -- with payslip_print_form='hidden', the
        button must not render, proving the button's own {% if %} actually
        reads payslip_link_visible rather than always rendering."""
        from app.settings import AppSettings
        run = posted_run_factory()
        run2 = self._post_run(client, run, login_user, accountant_user, db_session, main_branch)
        AppSettings.set_setting('payslip_print_form', 'hidden', updated_by='test')
        db.session.commit()

        resp = client.get(f'/payroll/runs/{run2.id}')
        assert resp.status_code == 200
        assert b'Print All Payslips' not in resp.data
