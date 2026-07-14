"""PayrollRun / PayrollRunLine models: period partial-unique-index guard,
line.calculate_amounts() delegation to the calc engine, header.calculate_totals().

The DB partial-unique index is the real guard (mirrors the CDV check-serial
pattern, tests/integration/test_cdv_check_serial.py). Exercised here via
conftest's create_all() (which builds the model's __table_args__ index) --
also verified against a real migrated cas.db copy, see task-6-report.md.
"""
import re
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.accounts.models import Account
from app.audit.models import AuditLog
from app.employees.models import Employee
from app.payroll.models import PayrollRun, PayrollRunLine
from app.payroll import service
from app.periods.models import AccountingPeriod
from app.posting.control_accounts import CONTROL_ACCOUNTS
from app.seeds.statutory_2026 import seed_statutory_2026
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _cells(row_html):
    """Visible text of each <td> in one <tr>...</tr> HTML fragment (nested
    tags like <a>/<span> stripped) -- order-preserving, so a caller can pin
    column ORDER, not just substring presence (render-assertions-miss-order-
    and-attributes)."""
    return [re.sub(r'<[^>]+>', '', c).strip()
            for c in re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.S)]


def _find_row(body, needle):
    """First <tr>...</tr> fragment containing `needle`."""
    for row in re.findall(r'<tr[^>]*>.*?</tr>', body, re.S):
        if needle in row:
            return row
    raise AssertionError(f'no <tr> found containing {needle!r}')


def _run(db_session, branch, run_number='PR-2026-06-0001', run_type='regular',
         pay_frequency='monthly', period_year=2026, period_month=6, semi_period=0,
         status='draft'):
    r = PayrollRun(
        run_number=run_number, branch_id=branch.id, run_type=run_type,
        pay_frequency=pay_frequency, period_year=period_year, period_month=period_month,
        semi_period=semi_period,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), pay_date=date(2026, 7, 5),
        semi_timing='second_cutoff', status=status,
    )
    db_session.add(r)
    return r


def _employee(db_session, branch, employee_no='EMP-001', pay_basis='monthly',
              basic_rate=Decimal('40000'), is_mwe=False):
    e = Employee(
        employee_no=employee_no, first_name='Juan', last_name='Dela Cruz',
        branch_id=branch.id, pay_basis=pay_basis, basic_rate=basic_rate,
        pay_frequency='monthly', is_minimum_wage=is_mwe, tax_status_code='S',
    )
    db_session.add(e); db_session.commit()
    return e


class TestPeriodUniqueIndex:
    def test_duplicate_nonvoided_period_rejected(self, db_session, main_branch):
        """Two non-voided runs for the same (branch, regular, monthly, 2026, 6, None)
        period key: the 2nd raises IntegrityError."""
        _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002', status='draft')
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_voiding_frees_the_period_slot(self, db_session, main_branch):
        """Voiding the first run frees the period key for a fresh run."""
        r1 = _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()

        r1.status = 'voided'
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002', status='draft')
        db_session.commit()   # no raise -- slot freed

    def test_different_branch_not_blocked(self, db_session, main_branch, branch_manila):
        """The unique key includes branch_id -- a 2nd branch may run the same period."""
        _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()

        _run(db_session, branch_manila, run_number='PR-2026-06-0002', status='draft')
        db_session.commit()   # no raise -- different branch

    def test_different_run_type_not_blocked(self, db_session, main_branch):
        """The unique key includes run_type -- a 13th-month run doesn't collide
        with a regular run in the same period."""
        _run(db_session, main_branch, run_number='PR-2026-06-0001',
             run_type='regular', status='draft')
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002',
             run_type='13th_month', status='draft')
        db_session.commit()   # no raise -- different run_type

    def test_semi_monthly_different_cutoff_not_blocked(self, db_session, main_branch):
        """semi_period is part of the unique key -- cutoff 1 and cutoff 2 of the
        same semi-monthly period are two distinct, valid runs."""
        _run(db_session, main_branch, run_number='PR-2026-06-0001',
             pay_frequency='semi_monthly', semi_period=1, status='draft')
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002',
             pay_frequency='semi_monthly', semi_period=2, status='draft')
        db_session.commit()   # no raise -- different cutoff

    def test_semi_monthly_same_cutoff_rejected(self, db_session, main_branch):
        """A 2nd non-voided run for the SAME semi-monthly cutoff is rejected --
        this is the case that would slip through if semi_period stayed NULL for
        every non-semi-monthly frequency and the DB engine's NULL-distinct
        semantics leaked into the semi-monthly rows too (it doesn't, since 1/2
        are real, comparable values either way; this test pins that)."""
        _run(db_session, main_branch, run_number='PR-2026-06-0001',
             pay_frequency='semi_monthly', semi_period=1, status='draft')
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002',
             pay_frequency='semi_monthly', semi_period=1, status='draft')
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_cancelled_also_frees_the_slot(self, db_session, main_branch):
        r1 = _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()

        r1.status = 'cancelled'
        db_session.commit()

        _run(db_session, main_branch, run_number='PR-2026-06-0002', status='draft')
        db_session.commit()   # no raise -- freed


class TestCalculateAmounts:
    def test_calculate_amounts_matches_compute_line(self, db_session, main_branch):
        """line.calculate_amounts() delegates to service.compute_line with the
        input dict built from the line's own snapshot cols + the run header's
        pay_frequency/period_end/semi_timing."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, basic_rate=Decimal('40000'))
        run = _run(db_session, main_branch)
        db_session.add(run); db_session.commit()

        line = PayrollRunLine(
            run_id=run.id, line_number=1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
            tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run.lines.append(line)
        db_session.commit()

        line.calculate_amounts()
        db_session.commit()

        expected = service.compute_line(dict(
            pay_basis='monthly', monthly_rate=Decimal('40000'), daily_rate=Decimal('40000'),
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'), is_mwe=False,
            pay_frequency='monthly', period_end=date(2026, 6, 30), semi_timing='second_cutoff',
            semi_period=0,
        ))

        assert line.basic_gross == expected['basic_gross']
        assert line.gross_pay == expected['gross_pay']
        assert line.taxable_comp == expected['taxable_comp']
        assert line.wht == expected['wht']
        assert line.net_pay == expected['net_pay']
        assert line.sss_ee == expected['statutory']['sss_ee']

    def test_mwe_line_is_wht_exempt(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, basic_rate=Decimal('12000'), is_mwe=True)
        run = _run(db_session, main_branch)
        db_session.add(run); db_session.commit()

        line = PayrollRunLine(
            run_id=run.id, line_number=1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
            is_mwe=True, days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run.lines.append(line)
        db_session.commit()

        line.calculate_amounts()

        assert line.taxable_comp == Decimal('0.00')
        assert line.wht == Decimal('0.00')
        assert line.wht_bracket_id is None


class TestCalculateTotals:
    def test_calculate_totals_sums_lines(self, db_session, main_branch):
        seed_statutory_2026()
        emp1 = _employee(db_session, main_branch, employee_no='EMP-001', basic_rate=Decimal('40000'))
        emp2 = _employee(db_session, main_branch, employee_no='EMP-002', basic_rate=Decimal('25000'))
        run = _run(db_session, main_branch)
        db_session.add(run); db_session.commit()

        for i, emp in enumerate((emp1, emp2), start=1):
            line = PayrollRunLine(
                run_id=run.id, line_number=i, employee_id=emp.id,
                employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
                is_mwe=False, days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
                taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
            )
            run.lines.append(line)
        db_session.commit()

        for line in run.lines:
            line.calculate_amounts()
        run.calculate_totals()
        db_session.commit()

        assert run.total_gross == sum((l.gross_pay for l in run.lines), Decimal('0.00'))
        assert run.total_wht == sum((l.wht for l in run.lines), Decimal('0.00'))
        assert run.total_net_pay == sum((l.net_pay for l in run.lines), Decimal('0.00'))
        assert run.total_net_pay > 0

    def test_line_cascade_delete_orphan(self, db_session, main_branch):
        """PayrollRunLine cascades delete-orphan from its parent run (mirrors
        the CDV line relationship's cascade setting)."""
        emp = _employee(db_session, main_branch)
        run = _run(db_session, main_branch)
        db_session.add(run); db_session.commit()

        line = PayrollRunLine(
            run_id=run.id, line_number=1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
        )
        run.lines.append(line)
        db_session.commit()
        line_id = line.id

        run.lines.remove(line)
        db_session.commit()

        assert db.session.get(PayrollRunLine, line_id) is None


class TestPayrollWorksheet:
    """Task 8: the worksheet slice -- payroll.new_run / payroll.edit_run.

    Covers the brief's Step 2 requirements: a draft POST with one monthly
    employee persists a PayrollRun + 1 computed line matching
    service.compute_line; staff can create/edit; posting into a closed
    AccountingPeriod is blocked.
    """

    def test_staff_creates_draft_run_with_one_monthly_employee(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp = Employee(
            employee_no='EMP-100', first_name='Ana', last_name='Reyes',
            branch_id=main_branch.id, pay_basis='monthly', basic_rate=Decimal('30000.00'),
            pay_frequency='monthly', is_minimum_wage=False, tax_status_code='S',
        )
        db_session.add(emp); db_session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.post('/payroll/runs/new', data={
            'run_type': 'regular', 'pay_frequency': 'monthly', 'semi_period': '0',
            'period_start': '2026-06-01', 'period_end': '2026-06-30', 'pay_date': '2026-07-05',
        }, follow_redirects=True)
        assert resp.status_code == 200

        run = PayrollRun.query.filter_by(branch_id=main_branch.id).first()
        assert run is not None
        # run_number reflects the ENTRY date (today), like CD/AP/JV numbering --
        # not the payroll PERIOD being processed (2026-06 in this test).
        from app.utils import ph_now
        today = ph_now()
        assert run.run_number.startswith(f'PR-{today.year}-{today.month:02d}-')
        assert run.status == 'draft'
        assert len(run.lines) == 1

        line = run.lines[0]
        assert line.employee_id == emp.id

        expected = service.compute_line(dict(
            pay_basis='monthly', monthly_rate=Decimal('30000.00'), daily_rate=Decimal('30000.00'),
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'), is_mwe=False,
            pay_frequency='monthly', period_end=date(2026, 6, 30), semi_timing=None, semi_period=0,
        ))
        assert line.basic_gross == expected['basic_gross']
        assert line.gross_pay == expected['gross_pay']
        assert line.wht == expected['wht']
        assert line.net_pay == expected['net_pay']

        assert run.total_net_pay == line.net_pay
        assert run.total_net_pay > Decimal('0.00')

        assert AuditLog.query.filter_by(
            module='payroll_run', action='create', record_id=run.id).count() == 1

    def test_closed_period_blocks_new_run(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp = Employee(
            employee_no='EMP-101', first_name='Ben', last_name='Cruz',
            branch_id=main_branch.id, pay_basis='monthly', basic_rate=Decimal('20000.00'),
            pay_frequency='monthly', tax_status_code='S',
        )
        db_session.add(emp); db_session.commit()

        period = AccountingPeriod.get_or_create_period(2026, 6)
        period.close_period(staff_user)

        login_user(client, 'staff', 'staff123')
        resp = client.post('/payroll/runs/new', data={
            'run_type': 'regular', 'pay_frequency': 'monthly', 'semi_period': '0',
            'period_start': '2026-06-01', 'period_end': '2026-06-30', 'pay_date': '2026-07-05',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'has been closed' in resp.data
        assert PayrollRun.query.filter_by(branch_id=main_branch.id).count() == 0

    def test_staff_edits_draft_run_and_totals_recompute(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp = Employee(
            employee_no='EMP-102', first_name='Cora', last_name='Diaz',
            branch_id=main_branch.id, pay_basis='daily', basic_rate=Decimal('750.00'),
            pay_frequency='monthly', tax_status_code='S',
        )
        db_session.add(emp); db_session.commit()

        login_user(client, 'staff', 'staff123')
        client.post('/payroll/runs/new', data={
            'run_type': 'regular', 'pay_frequency': 'monthly', 'semi_period': '0',
            'period_start': '2026-06-01', 'period_end': '2026-06-30', 'pay_date': '2026-07-05',
            f'line_{emp.id}_days': '10',
        }, follow_redirects=True)

        run = PayrollRun.query.filter_by(branch_id=main_branch.id).first()
        assert run is not None
        first_gross = run.lines[0].gross_pay
        assert run.lines[0].days == Decimal('10.00')

        resp = client.post(f'/payroll/runs/{run.id}/edit', data={
            'row_version': str(run.row_version),
            'run_type': 'regular', 'pay_frequency': 'monthly', 'semi_period': '0',
            'period_start': '2026-06-01', 'period_end': '2026-06-30', 'pay_date': '2026-07-05',
            f'line_{emp.id}_days': '22',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        run2 = db.session.get(PayrollRun, run.id)
        assert len(run2.lines) == 1
        assert run2.lines[0].days == Decimal('22.00')
        assert run2.lines[0].gross_pay > first_gross
        assert run2.total_net_pay == run2.lines[0].net_pay

        assert AuditLog.query.filter_by(
            module='payroll_run', action='update', record_id=run.id).count() == 1

    def test_viewer_cannot_create_draft_run(
            self, client, viewer_user, main_branch, login_user, db_session):
        viewer_user.branches.append(main_branch)
        db_session.commit()

        login_user(client, 'viewer', 'viewer123')
        resp = client.post('/payroll/runs/new', data={
            'run_type': 'regular', 'pay_frequency': 'monthly', 'semi_period': '0',
            'period_start': '2026-06-01', 'period_end': '2026-06-30', 'pay_date': '2026-07-05',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert PayrollRun.query.count() == 0


class TestRegisterAndDetailViews:
    """Task 9: register + run detail + JE preview -- view-only (no lifecycle
    transitions; a draft has no way to become posted/voided yet -- that's
    Task 10). Assertions check column ORDER and key ATTRIBUTES (href, badge
    class), not just substring presence, per render-assertions-miss-order-
    and-attributes.
    """

    def _line_for(self, db_session, run, emp):
        line = PayrollRunLine(
            run_id=run.id, line_number=len(run.lines) + 1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
            tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run.lines.append(line)
        db_session.commit()
        line.calculate_amounts()
        return line

    # ---- Register ----

    def test_register_lists_run_with_correct_totals_and_column_order(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp = _employee(db_session, main_branch, employee_no='EMP-901', basic_rate=Decimal('40000'))
        run = _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()
        self._line_for(db_session, run, emp)
        run.calculate_totals()
        db_session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.get('/payroll/runs')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        row = _find_row(body, run.run_number)
        cells = _cells(row)
        # Run Number, Branch, Type, Frequency, Period, Pay Date, Status, Gross, Deductions, Net Pay
        assert cells[0] == run.run_number
        assert cells[1] == main_branch.name
        assert cells[6] == 'Draft'
        deductions = run.total_gross - run.total_net_pay
        assert cells[7] == '{:,.2f}'.format(run.total_gross)
        assert cells[8] == '{:,.2f}'.format(deductions)
        assert cells[9] == '{:,.2f}'.format(run.total_net_pay)
        # Attributes: the run number is a real link to the detail route, and
        # the status cell carries the status-specific badge class.
        assert f'/payroll/runs/{run.id}"' in row
        assert 'badge-draft' in row

    def test_register_totals_footer_excludes_voided_run(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp1 = _employee(db_session, main_branch, employee_no='EMP-902', basic_rate=Decimal('40000'))
        run1 = _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()
        self._line_for(db_session, run1, emp1)
        run1.calculate_totals()
        db_session.commit()

        run1.status = 'voided'   # frees the period slot (mirrors test_voiding_frees_the_period_slot)
        db_session.commit()

        emp2 = _employee(db_session, main_branch, employee_no='EMP-903', basic_rate=Decimal('25000'))
        run2 = _run(db_session, main_branch, run_number='PR-2026-06-0002', status='draft')
        db_session.commit()
        self._line_for(db_session, run2, emp2)
        run2.calculate_totals()
        db_session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.get('/payroll/runs')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        row1 = _find_row(body, run1.run_number)
        cells1 = _cells(row1)
        assert cells1[7] == '—'
        assert cells1[8] == '—'
        assert cells1[9] == '—'
        assert 'badge-voided' in row1

        footer_match = re.search(r'<tfoot>.*?</tfoot>', body, re.S)
        assert footer_match, 'no <tfoot> found'
        footer = footer_match.group(0)
        assert 'Totals (1 non-voided run)' in footer
        assert '{:,.2f}'.format(run2.total_gross) in footer
        assert '{:,.2f}'.format(run2.total_gross - run2.total_net_pay) in footer
        assert '{:,.2f}'.format(run2.total_net_pay) in footer
        # The voided run's real (nonzero) totals must NOT leak into the footer sum.
        assert '{:,.2f}'.format(run1.total_gross + run2.total_gross) not in footer

    # ---- Detail: employee lines ----

    def test_detail_shows_employee_lines_with_column_order(
            self, client, staff_user, main_branch, login_user, db_session):
        seed_statutory_2026()
        staff_user.branches.append(main_branch)
        db_session.commit()

        emp = _employee(db_session, main_branch, employee_no='EMP-904', basic_rate=Decimal('40000'))
        run = _run(db_session, main_branch, run_number='PR-2026-06-0001', status='draft')
        db_session.commit()
        line = self._line_for(db_session, run, emp)
        run.calculate_totals()
        db_session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.get(f'/payroll/runs/{run.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        assert run.run_number in body
        assert main_branch.name in body

        row = _find_row(body, emp.full_name)
        cells = _cells(row)
        # Employee, Gross, SSS EE, PhilHealth EE, Pag-IBIG EE, WHT, Loans, Net Pay
        assert cells[0] == emp.full_name
        assert cells[1] == '{:,.2f}'.format(line.gross_pay)
        assert cells[2] == '{:,.2f}'.format(line.sss_ee)
        assert cells[3] == '{:,.2f}'.format(line.philhealth_ee)
        assert cells[4] == '{:,.2f}'.format(line.pagibig_ee)
        assert cells[5] == '{:,.2f}'.format(line.wht)
        assert cells[6] == '{:,.2f}'.format(line.sss_loan + line.pagibig_loan)
        assert cells[7] == '{:,.2f}'.format(line.net_pay)

    # ---- Detail: JE preview ----

    def test_detail_je_preview_ties_and_legs_match_header_buckets(
            self, client, staff_user, main_branch, login_user, db_session, posted_run_factory):
        run = posted_run_factory()
        staff_user.branches.append(main_branch)
        db_session.commit()

        preview = service.build_je_preview(run)
        assert preview['total_debit'] == preview['total_credit']
        assert preview['net_pay_plug'] == run.total_net_pay
        assert preview['balanced'] is True

        login_user(client, 'staff', 'staff123')
        resp = client.get(f'/payroll/runs/{run.id}')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        sal_row = _find_row(body, 'Salaries Expense')
        cells = _cells(sal_row)
        # Code, Account Title, Debit, Credit
        assert cells[0] == '50210'
        assert cells[1] == 'Salaries Expense'
        assert cells[2] == '{:,.2f}'.format(run.total_gross)
        assert cells[3] == '—'

        wht_row = _find_row(body, 'Withholding Tax')
        wcells = _cells(wht_row)
        assert wcells[0] == '20302'
        assert wcells[2] == '—'
        assert wcells[3] == '{:,.2f}'.format(run.total_wht)

        accrued_row = _find_row(body, 'Accrued Salaries')
        acells = _cells(accrued_row)
        assert acells[0] == '20501'
        assert acells[2] == '—'
        assert acells[3] == '{:,.2f}'.format(preview['net_pay_plug'])

        # detail.html has 2 tables (Employee Lines, then the JE preview) --
        # the JE preview's <tfoot> is the LAST one in the page.
        tfoots = re.findall(r'<tfoot>.*?</tfoot>', body, re.S)
        assert len(tfoots) == 2, f'expected 2 <tfoot> blocks, found {len(tfoots)}'
        je_tfoot = tfoots[-1]
        assert '{:,.2f}'.format(preview['total_debit']) in je_tfoot
        assert '{:,.2f}'.format(preview['total_credit']) in je_tfoot

    def test_detail_je_preview_unassigned_control_account_renders_placeholder_not_500(
            self, client, staff_user, main_branch, login_user, db_session, run_factory):
        run = run_factory()   # no control accounts assigned at all yet

        # Assign every payroll_* control account EXCEPT payroll_pagibig_er_expense
        # -- proves the assigned ones still render their real codes while the
        # ONE unassigned key renders a friendly placeholder, never a 500.
        to_assign = {
            'payroll_salaries_expense':      ('50210', 'Salaries Expense', 'Expense', 'Debit'),
            'payroll_sss_er_expense':        ('50212', 'SSS Employer Share Expense', 'Expense', 'Debit'),
            'payroll_philhealth_er_expense': ('50213', 'PhilHealth Employer Share Expense', 'Expense', 'Debit'),
            'payroll_wht_payable':           ('20302', 'Withholding Tax on Compensation Payable', 'Liability', 'Credit'),
            'payroll_sss_payable':           ('20402', 'SSS Contributions Payable', 'Liability', 'Credit'),
            'payroll_philhealth_payable':    ('20403', 'PhilHealth Contributions Payable', 'Liability', 'Credit'),
            'payroll_pagibig_payable':       ('20404', 'Pag-IBIG Contributions Payable', 'Liability', 'Credit'),
            'payroll_accrued_salaries':      ('20501', 'Accrued Salaries and Wages', 'Liability', 'Credit'),
        }
        for key, (code, name, atype, nb) in to_assign.items():
            db_session.add(Account(code=code, name=name, account_type=atype,
                                    classification=('Current Liability' if atype == 'Liability'
                                                    else 'Operating Expense'),
                                    normal_balance=nb))
        db_session.commit()
        for key, (code, *_rest) in to_assign.items():
            setting_key, _label = CONTROL_ACCOUNTS[key]
            AppSettings.set_setting(setting_key, code, updated_by='test')
        db_session.commit()

        staff_user.branches.append(main_branch)
        db_session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.get(f'/payroll/runs/{run.id}')
        assert resp.status_code == 200   # never a 500, even with an unassigned control account
        body = resp.get_data(as_text=True)

        unassigned_row = _find_row(body, 'Pag-IBIG Employer Share Expense')
        assert 'control account not assigned' in unassigned_row

        assigned_row = _find_row(body, 'Salaries Expense')
        acells = _cells(assigned_row)
        assert acells[0] == '50210'

        accrued_row = _find_row(body, 'Accrued Salaries')
        accells = _cells(accrued_row)
        assert accells[0] == '20501'
