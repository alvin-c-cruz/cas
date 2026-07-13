"""PayrollRun / PayrollRunLine models: period partial-unique-index guard,
line.calculate_amounts() delegation to the calc engine, header.calculate_totals().

The DB partial-unique index is the real guard (mirrors the CDV check-serial
pattern, tests/integration/test_cdv_check_serial.py). Exercised here via
conftest's create_all() (which builds the model's __table_args__ index) --
also verified against a real migrated cas.db copy, see task-6-report.md.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.audit.models import AuditLog
from app.employees.models import Employee
from app.payroll.models import PayrollRun, PayrollRunLine
from app.payroll import service
from app.periods.models import AccountingPeriod
from app.seeds.statutory_2026 import seed_statutory_2026

pytestmark = [pytest.mark.integration]


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
