"""R-06 Payroll Government Remittance Reports (Task 2+): SSS Contribution
Remittance reader-function tests. PhilHealth/Pag-IBIG/BIR 1601-C (Tasks 3-5)
add their own test classes to this same file, reusing app.reports.
payroll_remittances._posted_runs/_finalize via their own get_*_remittance
readers.
"""
from decimal import Decimal

import pytest

from app import db
from app.payroll.models import PayrollRun
from app.reports.payroll_remittances import (
    get_sss_remittance, get_philhealth_remittance, get_pagibig_remittance, get_bir_1601c,
)

pytestmark = [pytest.mark.integration]


def _post(run):
    run.status = 'posted'
    db.session.commit()


class TestSssRemittance:
    def test_single_posted_run_one_employee(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0001')
        _post(run)
        rows = get_sss_remittance(2026, 6, branch_id=run.branch_id)
        assert len(rows) == 2  # employee row + TOTAL row
        emp_row = rows[0]
        assert emp_row['employee_name'] == 'Juan Dela Cruz'
        assert emp_row['sss_ee'] > 0
        assert emp_row['sss_er'] > 0
        assert rows[-1]['employee_name'] == 'TOTAL'
        assert rows[-1]['sss_ee'] == emp_row['sss_ee']

    def test_two_semi_monthly_runs_sum_together(self, db_session, posted_semi_run_factory):
        run1 = posted_semi_run_factory('PR-2026-06-0001', semi_period=1, semi_timing='split_50_50')
        run2 = posted_semi_run_factory('PR-2026-06-0002', semi_period=2, semi_timing='split_50_50')
        _post(run1)
        _post(run2)
        rows = get_sss_remittance(2026, 6, branch_id=run1.branch_id)
        assert len(rows) == 2  # ONE employee (same employee, two cutoffs) + TOTAL
        emp_row = rows[0]
        expected = run1.lines[0].sss_ee + run2.lines[0].sss_ee
        assert emp_row['sss_ee'] == expected

    def test_voided_run_excluded(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0001')
        run.status = 'voided'
        db.session.commit()
        rows = get_sss_remittance(2026, 6, branch_id=run.branch_id)
        assert rows == []

    def test_thirteenth_month_run_excluded(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0001')
        run.run_type = '13th_month'
        run.status = 'posted'
        db.session.commit()
        rows = get_sss_remittance(2026, 6, branch_id=run.branch_id)
        assert rows == []

    def test_branch_filtering(self, db_session, run_factory, branch_manila):
        run = run_factory(run_number='PR-2026-06-0001')
        _post(run)
        rows = get_sss_remittance(2026, 6, branch_id=branch_manila.id)
        assert rows == []

    def test_missing_sss_no_still_appears_with_blank_id(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0001')
        run.lines[0].employee.sss_no = None
        _post(run)
        rows = get_sss_remittance(2026, 6, branch_id=run.branch_id)
        assert rows[0]['sss_no'] == ''

    def test_header_ties_to_run_totals(self, db_session, run_factory):
        """Report grand total must equal the sum of PayrollRun.total_sss_ee/er/ec
        for every included run -- catches a header/line drift bug in the payroll
        engine itself, not just a re-summing-of-its-own-lines bug."""
        run = run_factory(run_number='PR-2026-06-0001')
        _post(run)
        rows = get_sss_remittance(2026, 6, branch_id=run.branch_id)
        total_row = rows[-1]
        assert total_row['sss_ee'] == run.total_sss_ee
        assert total_row['sss_er'] == run.total_sss_er
        assert total_row['sss_ec'] == run.total_sss_ec


class TestPhilHealthRemittance:
    def test_single_posted_run_one_employee(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0002')
        _post(run)
        rows = get_philhealth_remittance(2026, 6, branch_id=run.branch_id)
        assert len(rows) == 2
        emp_row = rows[0]
        assert emp_row['philhealth_ee'] > 0
        assert emp_row['philhealth_er'] > 0
        assert rows[-1]['employee_name'] == 'TOTAL'

    def test_thirteenth_month_run_excluded(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0002')
        run.run_type = '13th_month'
        run.status = 'posted'
        db.session.commit()
        rows = get_philhealth_remittance(2026, 6, branch_id=run.branch_id)
        assert rows == []

    def test_header_ties_to_run_totals(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0002')
        _post(run)
        rows = get_philhealth_remittance(2026, 6, branch_id=run.branch_id)
        total_row = rows[-1]
        assert total_row['philhealth_ee'] == run.total_philhealth_ee
        assert total_row['philhealth_er'] == run.total_philhealth_er


class TestPagibigRemittance:
    def test_single_posted_run_one_employee(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0003')
        _post(run)
        rows = get_pagibig_remittance(2026, 6, branch_id=run.branch_id)
        assert len(rows) == 2
        emp_row = rows[0]
        assert emp_row['pagibig_ee'] > 0
        assert emp_row['pagibig_er'] > 0
        assert rows[-1]['employee_name'] == 'TOTAL'

    def test_thirteenth_month_run_excluded(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0003')
        run.run_type = '13th_month'
        run.status = 'posted'
        db.session.commit()
        rows = get_pagibig_remittance(2026, 6, branch_id=run.branch_id)
        assert rows == []

    def test_header_ties_to_run_totals(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0003')
        _post(run)
        rows = get_pagibig_remittance(2026, 6, branch_id=run.branch_id)
        total_row = rows[-1]
        assert total_row['pagibig_ee'] == run.total_pagibig_ee
        assert total_row['pagibig_er'] == run.total_pagibig_er


class TestBir1601c:
    def test_single_posted_regular_run(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0004', basic_rate=Decimal('100000.00'))
        _post(run)
        rows = get_bir_1601c(2026, 6, branch_id=run.branch_id)
        assert len(rows) == 2
        emp_row = rows[0]
        assert emp_row['tin'] == ''  # run_factory's Employee has no tin set by default
        assert rows[-1]['employee_name'] == 'TOTAL'

    def test_thirteenth_month_run_INCLUDED_unlike_other_three(self, db_session, run_factory):
        """The one report where a 13th_month run's WHT counts -- 13th-month pay
        above the statutory cap is taxable and withheld."""
        reg_run = run_factory(run_number='PR-2026-06-0004', basic_rate=Decimal('100000.00'))
        _post(reg_run)
        thirteenth_run = run_factory(run_number='PR-2026-06-0005', basic_rate=Decimal('100000.00'),
                                      employee=reg_run.lines[0].employee, run_type='13th_month')
        thirteenth_run.status = 'posted'
        db.session.commit()
        rows = get_bir_1601c(2026, 6, branch_id=reg_run.branch_id)
        # both runs share the same employee (run_factory always builds 'Juan Dela Cruz'),
        # so exactly one employee row + TOTAL -- but WHT from BOTH runs is summed in
        assert len(rows) == 2
        expected_wht = reg_run.lines[0].wht + thirteenth_run.lines[0].wht
        assert rows[0]['wht'] == expected_wht

    def test_header_ties_to_run_totals(self, db_session, run_factory):
        run = run_factory(run_number='PR-2026-06-0004', basic_rate=Decimal('100000.00'))
        _post(run)
        rows = get_bir_1601c(2026, 6, branch_id=run.branch_id)
        assert rows[-1]['wht'] == run.total_wht
