"""Shared fixtures for tests/payroll/ that need a fully built PayrollRun
(header + line(s)) rather than the bare model construction each individual
test file already does inline (test_lifecycle.py, test_control_accounts_payroll.py).

`app_ctx` is a thin alias over the root conftest's `db_session` (which already
pushes an app context + create_all()/drop_all() per test) -- it exists only so
tests/payroll/test_payroll_je.py can request it by the name used in the task
brief; it does not stand up a second Flask app.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.employees.models import Employee
from app.payroll.models import PayrollRun, PayrollRunLine
from app.posting.control_accounts import CONTROL_ACCOUNTS
from app.seeds.statutory_2026 import seed_statutory_2026
from app.settings import AppSettings


@pytest.fixture
def app_ctx(db_session):
    yield db_session


@pytest.fixture(autouse=True)
def _payroll_module_enabled(db_session):
    """Task 15 gates `payroll` behind MODULE_REGISTRY (optional, default_enabled=False).
    The rest of this package's tests (test_lifecycle.py, test_loans_13th.py, ...) predate
    that gating and drive payroll routes directly via `client`, so turn the package ON by
    default for every test under tests/payroll/ -- mirrors how other optional-module test
    suites (e.g. tests/integration/test_so_status.py) enable their module explicitly.
    tests/payroll/test_module_gating.py overrides this back to OFF within its own OFF-state
    tests (its assertion runs after this fixture's setup, so the explicit call wins)."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:payroll', '1')
    clear_module_config_cache()
    yield
    clear_module_config_cache()


# code -> (account_type, normal_balance) for the 11 payroll control accounts,
# used only by posted_run_factory to stand up matching GL accounts.
_PAYROLL_ACCOUNTS = {
    'payroll_salaries_expense':      ('50210', 'Salaries Expense', 'Expense', 'Debit'),
    'payroll_sss_er_expense':        ('50212', 'SSS Employer Share Expense', 'Expense', 'Debit'),
    'payroll_philhealth_er_expense': ('50213', 'PhilHealth Employer Share Expense', 'Expense', 'Debit'),
    'payroll_pagibig_er_expense':    ('50214', 'Pag-IBIG Employer Share Expense', 'Expense', 'Debit'),
    'payroll_wht_payable':           ('20302', 'Withholding Tax on Compensation Payable', 'Liability', 'Credit'),
    'payroll_sss_payable':           ('20402', 'SSS Contributions Payable', 'Liability', 'Credit'),
    'payroll_philhealth_payable':    ('20403', 'PhilHealth Contributions Payable', 'Liability', 'Credit'),
    'payroll_pagibig_payable':       ('20404', 'Pag-IBIG Contributions Payable', 'Liability', 'Credit'),
    'payroll_sss_loan_payable':      ('20405', 'SSS Salary/Calamity Loan Payable', 'Liability', 'Credit'),
    'payroll_pagibig_loan_payable':  ('20406', 'Pag-IBIG Loan Payable', 'Liability', 'Credit'),
    'payroll_accrued_salaries':      ('20501', 'Accrued Salaries and Wages', 'Liability', 'Credit'),
}


@pytest.fixture
def run_factory(app_ctx, main_branch):
    """Builds a PayrollRun (+ 1 PayrollRunLine, fully computed via
    line.calculate_amounts()/run.calculate_totals()) with realistic values and
    NO control accounts assigned. Requires the 2026 statutory tables, seeded
    once per call (seed_statutory_2026 guards against double-seeding)."""
    def _make(run_number='PR-2026-06-0001', basic_rate=Decimal('40000.00')):
        seed_statutory_2026()

        emp = Employee(
            employee_no='EMP-001', first_name='Juan', last_name='Dela Cruz',
            branch_id=main_branch.id, pay_basis='monthly', basic_rate=basic_rate,
            pay_frequency='monthly', is_minimum_wage=False, tax_status_code='S',
        )
        db.session.add(emp)
        db.session.commit()

        run = PayrollRun(
            run_number=run_number, branch_id=main_branch.id, run_type='regular',
            pay_frequency='monthly', period_year=2026, period_month=6, semi_period=0,
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            pay_date=date(2026, 7, 5), semi_timing='second_cutoff', status='draft',
        )
        db.session.add(run)
        db.session.flush()

        line = PayrollRunLine(
            run_id=run.id, line_number=1, employee_id=emp.id,
            employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
            tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
            days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run.lines.append(line)
        db.session.commit()

        line.calculate_amounts()
        run.calculate_totals()
        db.session.commit()
        return run
    return _make


@pytest.fixture
def posted_run_factory(run_factory):
    """Same as run_factory, but assigns all 11 payroll_* control accounts
    (via AppSettings.set_setting, mirroring what an accountant does through
    Company Settings -> Control Accounts) so post_payroll_je can fully resolve
    every leg. Name mirrors the "control accounts assigned" precondition, NOT
    run.status (the run itself is still 'draft' -- post_payroll_je doesn't
    require a posted run to build the JE; that gate lives in the view/task 10)."""
    def _make(run_number='PR-2026-06-0001', basic_rate=Decimal('40000.00')):
        for key, (code, name, atype, nb) in _PAYROLL_ACCOUNTS.items():
            account = Account(code=code, name=name, account_type=atype,
                               classification='Current Liability' if atype == 'Liability'
                               else 'Operating Expense',
                               normal_balance=nb)
            db.session.add(account)
        db.session.commit()

        for key, (code, _name, _atype, _nb) in _PAYROLL_ACCOUNTS.items():
            setting_key, _label = CONTROL_ACCOUNTS[key]
            AppSettings.set_setting(setting_key, code, updated_by='test')
        db.session.commit()

        return run_factory(run_number=run_number, basic_rate=basic_rate)
    return _make
