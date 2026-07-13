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
from app.employees.models import Employee
from app.payroll.models import PayrollRun, PayrollRunLine
from app.payroll import service
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
