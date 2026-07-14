"""EmployeeLoan + amortization deduction (Task 11, R-06 Payroll v1 P3 slice).

Covers three layers:
  - service.compute_line: the pure calc-engine cap (min(amortization, balance),
    clamped at 0 -- never negative, never an error for a fully paid-off loan).
  - PayrollRunLine.calculate_amounts(): looks up the employee's ACTIVE loan of
    each type, records which one (sss_loan_id/pagibig_loan_id), and feeds its
    amortization/balance into compute_line.
  - The post/void/cancel lifecycle: posting decrements EmployeeLoan.balance by
    the amount actually applied; cancelling restores the EXACT amount that was
    decremented (never a fresh recompute); voiding (draft-only) never touches
    a loan balance, since apply_loan_balances() never ran for a draft.

Does NOT touch 13th-month (Task 13's job) despite this file's name matching
the brief's prescribed filename (tests/payroll/test_loans_13th.py).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.employees.models import Employee
from app.journal_entries.models import JournalEntry
from app.payroll.models import EmployeeLoan, PayrollRun, PayrollRunLine
from app.payroll import service
from app.seeds.statutory_2026 import seed_statutory_2026
from app.utils.concurrency import claim_version

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Layer 1: service.compute_line -- pure calc-engine cap
# ---------------------------------------------------------------------------

class TestComputeLineLoanCap:
    def _line_inputs(self, **loan_kwargs):
        base = dict(
            pay_basis='monthly', monthly_rate=Decimal('30000'), days=0, hours=0,
            ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
            is_mwe=False, pay_frequency='monthly', period_end=date(2026, 6, 30),
            semi_timing='second_cutoff',
        )
        base.update(loan_kwargs)
        return base

    def test_full_amortization_when_balance_sufficient(self, db_session):
        seed_statutory_2026()
        line = service.compute_line(self._line_inputs(
            sss_loan_amortization=Decimal('500'), sss_loan_balance=Decimal('5000')))
        assert line['sss_loan'] == Decimal('500.00')

    def test_capped_at_remaining_balance_when_amortization_exceeds_it(self, db_session):
        """A loan in its final month: amortization (800) > remaining balance
        (300) -- deducts ONLY the 300 remaining, not the full 800."""
        seed_statutory_2026()
        line = service.compute_line(self._line_inputs(
            sss_loan_amortization=Decimal('800'), sss_loan_balance=Decimal('300')))
        assert line['sss_loan'] == Decimal('300.00')

    def test_fully_paid_loan_deducts_zero_not_negative_not_error(self, db_session):
        seed_statutory_2026()
        line = service.compute_line(self._line_inputs(
            sss_loan_amortization=Decimal('500'), sss_loan_balance=Decimal('0')))
        assert line['sss_loan'] == Decimal('0.00')

    def test_both_loan_types_deduct_independently(self, db_session):
        seed_statutory_2026()
        line = service.compute_line(self._line_inputs(
            sss_loan_amortization=Decimal('500'), sss_loan_balance=Decimal('5000'),
            pagibig_loan_amortization=Decimal('200'), pagibig_loan_balance=Decimal('150')))
        assert line['sss_loan'] == Decimal('500.00')
        assert line['pagibig_loan'] == Decimal('150.00')   # capped

    def test_no_loan_keys_defaults_to_zero(self, db_session):
        """Backward compatible with every pre-Task-11 caller that never passes
        the loan keys at all (e.g. every existing test_calc_engine.py case)."""
        seed_statutory_2026()
        line = service.compute_line(self._line_inputs())
        assert line['sss_loan'] == Decimal('0.00')
        assert line['pagibig_loan'] == Decimal('0.00')

    def test_loan_deducted_from_net_pay(self, db_session):
        seed_statutory_2026()
        no_loan = service.compute_line(self._line_inputs())
        with_loan = service.compute_line(self._line_inputs(
            sss_loan_amortization=Decimal('500'), sss_loan_balance=Decimal('5000')))
        assert with_loan['net_pay'] == no_loan['net_pay'] - Decimal('500.00')


# ---------------------------------------------------------------------------
# Layer 2: PayrollRunLine.calculate_amounts() -- loan lookup + FK association
# ---------------------------------------------------------------------------

def _employee(db_session, branch, employee_no='EMP-LOAN-1', basic_rate=Decimal('30000')):
    e = Employee(
        employee_no=employee_no, first_name='Rico', last_name='Santos',
        branch_id=branch.id, pay_basis='monthly', basic_rate=basic_rate,
        pay_frequency='monthly', is_minimum_wage=False, tax_status_code='S',
    )
    db_session.add(e)
    db_session.commit()
    return e


def _run(db_session, branch, run_number='PR-2026-06-0001', status='draft'):
    r = PayrollRun(
        run_number=run_number, branch_id=branch.id, run_type='regular',
        pay_frequency='monthly', period_year=2026, period_month=6, semi_period=0,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), pay_date=date(2026, 7, 5),
        semi_timing='second_cutoff', status=status,
    )
    db_session.add(r)
    db_session.commit()
    return r


def _line(db_session, run, emp):
    line = PayrollRunLine(
        run_id=run.id, line_number=len(run.lines) + 1, employee_id=emp.id,
        employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
        tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
        days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
    )
    run.lines.append(line)
    db_session.commit()
    return line


class TestCalculateAmountsLoanLookup:
    def test_active_loan_is_found_capped_and_recorded_on_line(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch)
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('300'),
                             status='active')
        db_session.add(loan)
        db_session.commit()

        run = _run(db_session, main_branch)
        line = _line(db_session, run, emp)
        line.calculate_amounts()

        assert line.sss_loan_id == loan.id
        assert line.sss_loan == Decimal('300.00')   # capped at remaining balance

    def test_inactive_loan_is_ignored(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch)
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('300'),
                             status='paid')
        db_session.add(loan)
        db_session.commit()

        run = _run(db_session, main_branch)
        line = _line(db_session, run, emp)
        line.calculate_amounts()

        assert line.sss_loan_id is None
        assert line.sss_loan == Decimal('0.00')

    def test_no_loan_at_all_is_a_clean_zero(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch)
        run = _run(db_session, main_branch)
        line = _line(db_session, run, emp)
        line.calculate_amounts()

        assert line.sss_loan_id is None
        assert line.pagibig_loan_id is None
        assert line.sss_loan == Decimal('0.00')
        assert line.pagibig_loan == Decimal('0.00')

    def test_only_one_active_loan_per_employee_per_type_enforced(self, db_session, main_branch):
        """The partial unique index (uq_employee_loan_active_per_type) is what
        makes calculate_amounts()'s plain filter_by(...).first() lookup
        well-defined -- a 2nd ACTIVE sss loan for the same employee is rejected."""
        from sqlalchemy.exc import IntegrityError

        emp = _employee(db_session, main_branch)
        db_session.add(EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('5000'),
                                     monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                                     status='active'))
        db_session.commit()

        db_session.add(EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('3000'),
                                     monthly_amortization=Decimal('300'), balance=Decimal('3000'),
                                     status='active'))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# Layer 3: run totals + JE posting to 20405/20406
# ---------------------------------------------------------------------------

class TestRunTotalsAndJEPosting:
    def test_run_totals_and_je_book_sss_and_pagibig_loan_payable(
            self, db_session, main_branch, posted_run_factory):
        run = posted_run_factory()   # 1 line, control accounts assigned
        emp_id = run.lines[0].employee_id

        db_session.add(EmployeeLoan(employee_id=emp_id, loan_type='sss', principal=Decimal('6000'),
                                     monthly_amortization=Decimal('500'), balance=Decimal('4000'),
                                     status='active'))
        db_session.add(EmployeeLoan(employee_id=emp_id, loan_type='pagibig', principal=Decimal('2000'),
                                     monthly_amortization=Decimal('200'), balance=Decimal('2000'),
                                     status='active'))
        db_session.commit()

        run.lines[0].calculate_amounts()
        run.calculate_totals()
        db_session.commit()

        assert run.total_sss_loan == Decimal('500.00')
        assert run.total_pagibig_loan == Decimal('200.00')

        je = service.post_payroll_je(run)
        sss_loan_line = next(l for l in je.lines if l.account.code == '20405')
        pagibig_loan_line = next(l for l in je.lines if l.account.code == '20406')
        assert sss_loan_line.credit_amount == run.total_sss_loan
        assert pagibig_loan_line.credit_amount == run.total_pagibig_loan


# ---------------------------------------------------------------------------
# Layer 4: lifecycle -- post decrements, cancel restores exactly, void no-ops
# ---------------------------------------------------------------------------

class TestLoanBalanceLifecycle:
    def _login_accountant(self, client, login_user, accountant_user, db_session):
        db_session.commit()
        login_user(client, 'accountant', 'accountant123')

    def _build_postable_run_with_loan(self, db_session, main_branch, posted_run_factory,
                                       amortization=Decimal('500'), balance=Decimal('4000')):
        run = posted_run_factory()
        emp_id = run.lines[0].employee_id
        loan = EmployeeLoan(employee_id=emp_id, loan_type='sss', principal=Decimal('6000'),
                             monthly_amortization=amortization, balance=balance, status='active')
        db_session.add(loan)
        db_session.commit()

        run.lines[0].calculate_amounts()
        run.calculate_totals()
        db_session.commit()
        return run, loan

    def test_post_decrements_loan_balance_by_amount_actually_applied(
            self, client, accountant_user, main_branch, login_user, db_session,
            posted_run_factory):
        """Amortization (500) < balance (4000) -- the FULL scheduled amount
        applies. Pins the ordinary (non-capped) case at the lifecycle level."""
        run, loan = self._build_postable_run_with_loan(
            db_session, main_branch, posted_run_factory,
            amortization=Decimal('500'), balance=Decimal('4000'))
        self._login_accountant(client, login_user, accountant_user, db_session)

        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.balance == Decimal('3500.00')   # 4000 - 500

    def test_post_decrements_by_capped_amount_not_full_amortization(
            self, client, accountant_user, main_branch, login_user, db_session,
            posted_run_factory):
        """MUTATION-PROOF for the cap: amortization (800) > balance (300).
        If the implementation decremented by the full scheduled amortization
        instead of the capped applied amount, balance would go to -500 --
        this pins it at exactly 0.00."""
        run, loan = self._build_postable_run_with_loan(
            db_session, main_branch, posted_run_factory,
            amortization=Decimal('800'), balance=Decimal('300'))
        self._login_accountant(client, login_user, accountant_user, db_session)

        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.balance == Decimal('0.00')
        assert loan2.balance >= Decimal('0.00'), 'balance must never go negative'

    def test_fully_paid_loan_is_untouched_by_posting(
            self, client, accountant_user, main_branch, login_user, db_session,
            posted_run_factory):
        run, loan = self._build_postable_run_with_loan(
            db_session, main_branch, posted_run_factory,
            amortization=Decimal('500'), balance=Decimal('0'))
        self._login_accountant(client, login_user, accountant_user, db_session)

        resp = client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.balance == Decimal('0.00')

    def test_cancel_restores_the_exact_decremented_amount(
            self, client, accountant_user, main_branch, login_user, db_session,
            posted_run_factory):
        run, loan = self._build_postable_run_with_loan(
            db_session, main_branch, posted_run_factory,
            amortization=Decimal('800'), balance=Decimal('300'))
        original_balance = loan.balance
        self._login_accountant(client, login_user, accountant_user, db_session)

        client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        db.session.expire_all()
        loan_after_post = db.session.get(EmployeeLoan, loan.id)
        assert loan_after_post.balance == Decimal('0.00')

        resp = client.post(f'/payroll/runs/{run.id}/cancel', data={
            'cancel_reason': 'Testing exact loan-balance restore on cancel',
            'reversal_date': '2026-06-30',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        loan_after_cancel = db.session.get(EmployeeLoan, loan.id)
        assert loan_after_cancel.balance == original_balance   # exactly restored: 300.00

    def test_cancel_restores_the_stored_amount_not_a_recompute_after_rate_change(
            self, client, accountant_user, main_branch, login_user, db_session,
            posted_run_factory):
        """MUTATION-PROOF for the reversal: mutate the loan's
        monthly_amortization AFTER posting but BEFORE cancelling. If the
        implementation re-derived the restore amount from
        loan.monthly_amortization at cancel time instead of using the
        amount stored on the line at post time, the restored balance would
        reflect the NEW (600) amortization, not the amount actually applied
        (500) -- this pins the restore to the ORIGINAL 500."""
        run, loan = self._build_postable_run_with_loan(
            db_session, main_branch, posted_run_factory,
            amortization=Decimal('500'), balance=Decimal('4000'))
        self._login_accountant(client, login_user, accountant_user, db_session)

        client.post(f'/payroll/runs/{run.id}/post', data={
            'row_version': str(run.row_version),
        }, follow_redirects=True)
        db.session.expire_all()
        loan_after_post = db.session.get(EmployeeLoan, loan.id)
        assert loan_after_post.balance == Decimal('3500.00')

        # Drift the loan's amortization AFTER post, before cancel.
        loan_after_post.monthly_amortization = Decimal('600.00')
        db.session.commit()

        client.post(f'/payroll/runs/{run.id}/cancel', data={
            'cancel_reason': 'Proving the restore ignores a post-facto rate change',
            'reversal_date': '2026-06-30',
        }, follow_redirects=True)

        db.session.expire_all()
        loan_after_cancel = db.session.get(EmployeeLoan, loan.id)
        # 3500 + 500 (the ORIGINAL applied amount) = 4000, NOT 3500 + 600 = 4100.
        assert loan_after_cancel.balance == Decimal('4000.00')

    def test_void_draft_run_does_not_touch_loan_balance(
            self, client, staff_user, main_branch, login_user, db_session, run_factory):
        """A draft run's line carries a computed sss_loan PREVIEW amount
        (calculate_amounts() runs on every draft save) but apply_loan_balances()
        never ran for it (that only happens inside post_run) -- voiding must
        leave the loan's balance completely untouched, proving void_run does
        NOT call restore_loan_balances (which would incorrectly credit an
        amount that was never debited)."""
        run = run_factory()
        emp_id = run.lines[0].employee_id
        loan = EmployeeLoan(employee_id=emp_id, loan_type='sss', principal=Decimal('6000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('4000'),
                             status='active')
        db_session.add(loan)
        db_session.commit()

        run.lines[0].calculate_amounts()   # preview only -- balance untouched
        db_session.commit()
        assert run.lines[0].sss_loan == Decimal('500.00')   # preview amount is nonzero

        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/runs/{run.id}/void', data={
            'void_reason': 'Voiding a draft that has a loan-preview amount',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        run2 = db.session.get(PayrollRun, run.id)
        assert run2.status == 'voided'
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.balance == Decimal('4000.00'), 'draft void must never touch a loan balance'
