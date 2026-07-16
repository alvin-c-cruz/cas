"""Unit tests for service.ytd_totals — YTD aggregation for the payslip's YTD block."""
from datetime import date
from decimal import Decimal

from app import db
from app.employees.models import Employee
from app.payroll import service
from app.payroll.models import PayrollRun, PayrollRunLine


def _make_run(branch_id, run_number, period_month, semi_period=0, status='posted',
              run_type='regular', period_year=2026):
    run = PayrollRun(
        run_number=run_number, branch_id=branch_id, run_type=run_type,
        pay_frequency='monthly' if semi_period == 0 else 'semi_monthly',
        period_year=period_year, period_month=period_month, semi_period=semi_period,
        period_start=date(period_year, period_month, 1),
        period_end=date(period_year, period_month, 28),
        pay_date=date(period_year, period_month, 28), semi_timing='second_cutoff',
        status=status,
    )
    db.session.add(run)
    db.session.flush()
    return run


def _make_line(run, employee_id, employee_name, gross=Decimal('30000.00')):
    line = PayrollRunLine(
        run_id=run.id, line_number=1, employee_id=employee_id,
        employee_name=employee_name, pay_basis='monthly', rate=gross,
        basic_gross=gross, gross_pay=gross, taxable_comp=gross,
        wht=Decimal('1000.00'), sss_ee=Decimal('900.00'),
        philhealth_ee=Decimal('500.00'), pagibig_ee=Decimal('100.00'),
        net_pay=gross - Decimal('2500.00'),
    )
    db.session.add(line)
    db.session.commit()
    return line


def test_single_run_returns_its_own_figures(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add(emp)
    db.session.commit()
    run = _make_run(main_branch.id, 'PR-2026-01-0001', 1)
    _make_line(run, emp.id, emp.full_name)

    ytd = service.ytd_totals(emp.id, run)
    assert ytd['gross_pay'] == Decimal('30000.00')
    assert ytd['wht'] == Decimal('1000.00')
    assert ytd['net_pay'] == Decimal('27500.00')


def test_multiple_runs_sum_correctly(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add(emp)
    db.session.commit()
    jan = _make_run(main_branch.id, 'PR-2026-01-0001', 1)
    _make_line(jan, emp.id, emp.full_name, gross=Decimal('30000.00'))
    feb = _make_run(main_branch.id, 'PR-2026-02-0001', 2)
    _make_line(feb, emp.id, emp.full_name, gross=Decimal('30000.00'))

    ytd = service.ytd_totals(emp.id, feb)
    assert ytd['gross_pay'] == Decimal('60000.00')
    assert ytd['wht'] == Decimal('2000.00')


def test_semi_monthly_ordering_same_month_both_cutoffs_count(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='semi_monthly')
    db.session.add(emp)
    db.session.commit()
    cutoff1 = _make_run(main_branch.id, 'PR-2026-01-0001', 1, semi_period=1)
    _make_line(cutoff1, emp.id, emp.full_name, gross=Decimal('15000.00'))
    cutoff2 = _make_run(main_branch.id, 'PR-2026-01-0002', 1, semi_period=2)
    _make_line(cutoff2, emp.id, emp.full_name, gross=Decimal('15000.00'))

    ytd = service.ytd_totals(emp.id, cutoff2)
    assert ytd['gross_pay'] == Decimal('30000.00'), \
        'both cutoffs of the same month must count when querying through cutoff 2'

    ytd_at_first_cutoff = service.ytd_totals(emp.id, cutoff1)
    assert ytd_at_first_cutoff['gross_pay'] == Decimal('15000.00'), \
        'querying through cutoff 1 must NOT include cutoff 2 (future relative to it)'


def test_voided_run_excluded(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add(emp)
    db.session.commit()
    jan = _make_run(main_branch.id, 'PR-2026-01-0001', 1, status='voided')
    _make_line(jan, emp.id, emp.full_name)
    feb = _make_run(main_branch.id, 'PR-2026-02-0001', 2)
    _make_line(feb, emp.id, emp.full_name)

    ytd = service.ytd_totals(emp.id, feb)
    assert ytd['gross_pay'] == Decimal('30000.00'), 'the voided January run must not count'


def test_different_employee_excluded(app_ctx, main_branch):
    emp1 = Employee(employee_no='E1', first_name='A', last_name='B',
                     branch_id=main_branch.id, pay_basis='monthly',
                     basic_rate=Decimal('30000'), pay_frequency='monthly')
    emp2 = Employee(employee_no='E2', first_name='C', last_name='D',
                     branch_id=main_branch.id, pay_basis='monthly',
                     basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add_all([emp1, emp2])
    db.session.commit()
    jan = _make_run(main_branch.id, 'PR-2026-01-0001', 1)
    _make_line(jan, emp1.id, emp1.full_name)
    feb = _make_run(main_branch.id, 'PR-2026-02-0001', 2)
    _make_line(feb, emp2.id, emp2.full_name)

    ytd = service.ytd_totals(emp2.id, feb)
    assert ytd['gross_pay'] == Decimal('30000.00'), "emp1's January run must not leak into emp2's YTD"


def test_prior_year_run_excluded(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add(emp)
    db.session.commit()
    dec_2025 = _make_run(main_branch.id, 'PR-2025-12-0001', 12, period_year=2025)
    _make_line(dec_2025, emp.id, emp.full_name)
    jan_2026 = _make_run(main_branch.id, 'PR-2026-01-0001', 1, period_year=2026)
    _make_line(jan_2026, emp.id, emp.full_name)

    ytd = service.ytd_totals(emp.id, jan_2026)
    assert ytd['gross_pay'] == Decimal('30000.00'), '2025 must not bleed into a 2026 YTD figure'


def test_thirteenth_month_run_excluded(app_ctx, main_branch):
    emp = Employee(employee_no='E1', first_name='A', last_name='B',
                    branch_id=main_branch.id, pay_basis='monthly',
                    basic_rate=Decimal('30000'), pay_frequency='monthly')
    db.session.add(emp)
    db.session.commit()
    jan = _make_run(main_branch.id, 'PR-2026-01-0001', 1)
    _make_line(jan, emp.id, emp.full_name, gross=Decimal('30000.00'))
    thirteenth = _make_run(main_branch.id, 'PR13-2026-0001', 12, run_type='13th_month')
    _make_line(thirteenth, emp.id, emp.full_name, gross=Decimal('30000.00'))

    ytd = service.ytd_totals(emp.id, thirteenth)
    assert ytd['gross_pay'] == Decimal('30000.00'), \
        'the 13th-month run itself must not contribute to the regular-run YTD sum'
