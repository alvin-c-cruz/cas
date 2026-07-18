"""Payroll government remittance reports: SSS, PhilHealth, Pag-IBIG, BIR 1601-C.

Every report is computed live from POSTED PayrollRun/PayrollRunLine rows for a
given branch/year/month -- no new table, mirrors app/reports/bir.py's reader
pattern exactly (a sorted list of per-employee dicts with a trailing TOTAL row).

SSS/PhilHealth/Pag-IBIG restrict to run_type == 'regular': a 13th_month run's
lines never populate sss_ee/philhealth_ee/pagibig_ee (those contributions are
only computed on regular pay), so including 13th_month runs would be a silent
no-op at best -- the filter makes the exclusion an explicit design decision.
BIR 1601-C (see the sibling function below) is the one exception: 13th-month
pay above the statutory cap IS taxable and withheld, so it includes both
run_type values.
"""
from decimal import Decimal

from app.payroll.models import PayrollRun


def _posted_runs(year, month, branch_id, run_types):
    """Posted PayrollRun rows for a given period/branch, restricted to
    `run_types` (e.g. ['regular'] or ['regular', '13th_month']). Shared by
    every get_*_remittance reader in this module -- do not redefine."""
    query = PayrollRun.query.filter(
        PayrollRun.status == 'posted',
        PayrollRun.run_type.in_(run_types),
        PayrollRun.period_year == year,
        PayrollRun.period_month == month,
    )
    if branch_id is not None:
        query = query.filter(PayrollRun.branch_id == branch_id)
    return query.all()


def _finalize(rows, name_key='employee_name'):
    """rows: dict keyed by employee_id -> per-employee dict. Returns a list
    sorted by `name_key`, with a trailing {name_key: 'TOTAL', ...summed
    Decimal keys} row appended -- mirrors app/reports/bir.py's summary
    pattern. Shared by every get_*_remittance reader in this module -- do
    not redefine."""
    summary = sorted(rows.values(), key=lambda x: x[name_key])
    if summary:
        numeric = [k for k in summary[0] if isinstance(summary[0][k], Decimal)]
        totals = {k: '' for k in summary[0] if not isinstance(summary[0][k], Decimal)}
        totals[name_key] = 'TOTAL'
        totals.update({k: sum(s[k] for s in summary) for k in numeric})
        summary.append(totals)
    return summary


def get_sss_remittance(year, month, branch_id=None):
    """SSS Contribution Collection List: EE + ER + EC per employee."""
    rows = {}
    for run in _posted_runs(year, month, branch_id, ['regular']):
        for line in run.lines:
            emp = line.employee
            r = rows.setdefault(line.employee_id, {
                'employee_no': emp.employee_no if emp else '',
                'employee_name': line.employee_name,
                'sss_no': (emp.sss_no if emp else '') or '',
                'sss_ee': Decimal('0.00'),
                'sss_er': Decimal('0.00'),
                'sss_ec': Decimal('0.00'),
                'total': Decimal('0.00'),
            })
            r['sss_ee'] += line.sss_ee
            r['sss_er'] += line.sss_er
            r['sss_ec'] += line.sss_ec
            r['total'] += line.sss_ee + line.sss_er + line.sss_ec
    return _finalize(rows)


def get_philhealth_remittance(year, month, branch_id=None):
    """PhilHealth Employer's Remittance Report: EE + ER premium per employee."""
    rows = {}
    for run in _posted_runs(year, month, branch_id, ['regular']):
        for line in run.lines:
            emp = line.employee
            r = rows.setdefault(line.employee_id, {
                'employee_no': emp.employee_no if emp else '',
                'employee_name': line.employee_name,
                'philhealth_no': (emp.philhealth_no if emp else '') or '',
                'philhealth_ee': Decimal('0.00'),
                'philhealth_er': Decimal('0.00'),
                'total': Decimal('0.00'),
            })
            r['philhealth_ee'] += line.philhealth_ee
            r['philhealth_er'] += line.philhealth_er
            r['total'] += line.philhealth_ee + line.philhealth_er
    return _finalize(rows)


def get_pagibig_remittance(year, month, branch_id=None):
    """Pag-IBIG Monthly Contribution Remittance Form: EE + ER share per employee."""
    rows = {}
    for run in _posted_runs(year, month, branch_id, ['regular']):
        for line in run.lines:
            emp = line.employee
            r = rows.setdefault(line.employee_id, {
                'employee_no': emp.employee_no if emp else '',
                'employee_name': line.employee_name,
                'pagibig_no': (emp.pagibig_no if emp else '') or '',
                'pagibig_ee': Decimal('0.00'),
                'pagibig_er': Decimal('0.00'),
                'total': Decimal('0.00'),
            })
            r['pagibig_ee'] += line.pagibig_ee
            r['pagibig_er'] += line.pagibig_er
            r['total'] += line.pagibig_ee + line.pagibig_er
    return _finalize(rows)


def get_bir_1601c(year, month, branch_id=None):
    """BIR 1601-C: Monthly Remittance Return of Income Taxes Withheld on
    Compensation. Unlike the other three reports, includes BOTH run_type
    values -- 13th-month pay in excess of the statutory cap is taxable and
    withheld, so its WHT must be remitted here even though it never
    contributes to SSS/PhilHealth/Pag-IBIG."""
    rows = {}
    for run in _posted_runs(year, month, branch_id, ['regular', '13th_month']):
        for line in run.lines:
            emp = line.employee
            r = rows.setdefault(line.employee_id, {
                'employee_no': emp.employee_no if emp else '',
                'employee_name': line.employee_name,
                'tin': (emp.tin if emp else '') or '',
                'taxable_comp': Decimal('0.00'),
                'wht': Decimal('0.00'),
            })
            r['taxable_comp'] += line.taxable_comp
            r['wht'] += line.wht
    return _finalize(rows)
