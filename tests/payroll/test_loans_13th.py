"""EmployeeLoan + amortization deduction (Task 11, R-06 Payroll v1 P3 slice)
+ the Loan Editor UI (Task 12).

Covers three layers from Task 11:
  - service.compute_line: the pure calc-engine cap (min(amortization, balance),
    clamped at 0 -- never negative, never an error for a fully paid-off loan).
  - PayrollRunLine.calculate_amounts(): looks up the employee's ACTIVE loan of
    each type, records which one (sss_loan_id/pagibig_loan_id), and feeds its
    amortization/balance into compute_line.
  - The post/void/cancel lifecycle: posting decrements EmployeeLoan.balance by
    the amount actually applied; cancelling restores the EXACT amount that was
    decremented (never a fresh recompute); voiding (draft-only) never touches
    a loan balance, since apply_loan_balances() never ran for a draft.

Plus a fifth layer from Task 12 (the loan editor UI, appended below): list/
create/edit render (order + attributes), branch scoping via employee.branch_id,
audit logging on every write, the friendly duplicate-active-loan handling, the
no-JS-popup delete (blocked when payroll history exists), and the
_claim_loan_edit concurrency guard (see payroll.views for the design
reasoning -- EmployeeLoan is NOT RowVersioned; see that module's docstring).

Plus a sixth layer from Task 13 (13th-month, appended below): YTD basic
aggregation from posted regular runs only (draft/voided/cancelled excluded),
per-line override precedence, WHT computed only on the taxable excess over
service.THIRTEENTH_MONTH_EXEMPTION (P90,000), and JE posting with zero
statutory/loan legs.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.audit.models import AuditLog
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


# ---------------------------------------------------------------------------
# Layer 5: the Loan Editor UI (Task 12) -- list/create/edit render, branch
# scope, audit log, friendly duplicate-active-loan handling, no-JS-popup
# delete, and the _claim_loan_edit concurrency guard.
# ---------------------------------------------------------------------------

def _cells(row_html):
    """Visible text of each <td> in one <tr>...</tr> HTML fragment (nested
    tags like <a>/<span> stripped) -- order-preserving, so a caller can pin
    column ORDER, not just substring presence (render-assertions-miss-order-
    and-attributes). Duplicated from test_lifecycle.py's own copy -- this
    suite has no shared render-test-helper module to import it from."""
    return [re.sub(r'<[^>]+>', '', c).strip()
            for c in re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.S)]


def _find_row(body, needle):
    """First <tr>...</tr> fragment containing `needle`."""
    for row in re.findall(r'<tr[^>]*>.*?</tr>', body, re.S):
        if needle in row:
            return row
    raise AssertionError(f'no <tr> found containing {needle!r}')


def _other_branch_employee(db_session, branch, employee_no='EMP-OTHER'):
    e = Employee(
        employee_no=employee_no, first_name='Ana', last_name='Reyes',
        branch_id=branch.id, pay_basis='monthly', basic_rate=Decimal('20000'),
        pay_frequency='monthly', is_minimum_wage=False, tax_status_code='S',
    )
    db_session.add(e)
    db_session.commit()
    return e


class TestLoanListRender:
    def test_list_shows_loan_columns_in_order_with_badge_and_progress(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-UI-1')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000.00'),
                             monthly_amortization=Decimal('500.00'), balance=Decimal('3500.00'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.get('/payroll/loans')
        assert resp.status_code == 200
        body = resp.data.decode()

        row = _find_row(body, emp.full_name)
        cells = _cells(row)
        # Employee, Type, Principal, Amortization, Balance, Status, Actions
        assert cells[0] == emp.full_name
        assert cells[1] == 'SSS'
        assert cells[2] == '6,000.00'
        assert cells[3] == '500.00'
        assert '3,500.00' in cells[4]
        assert cells[5] == 'Active'

        # Progress bar reflects amount paid off: (6000-3500)/6000 = 41% (floor).
        assert 'progress-fill' in row
        assert 'width:41%' in row
        # Status-specific badge class, not a generic default.
        assert 'class="badge badge-active"' in row

    def test_list_is_branch_scoped_to_accessible_branches(
            self, client, staff_user, main_branch, branch_manila, login_user, db_session):
        emp_main = _employee(db_session, main_branch, employee_no='EMP-UI-MAIN')
        emp_mnl = _other_branch_employee(db_session, branch_manila, employee_no='EMP-UI-MNL')

        db_session.add(EmployeeLoan(employee_id=emp_main.id, loan_type='sss',
                                     principal=Decimal('5000'), monthly_amortization=Decimal('500'),
                                     balance=Decimal('5000'), status='active'))
        db_session.add(EmployeeLoan(employee_id=emp_mnl.id, loan_type='sss',
                                     principal=Decimal('4000'), monthly_amortization=Decimal('400'),
                                     balance=Decimal('4000'), status='active'))
        staff_user.branches.append(main_branch)   # NOT branch_manila
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.get('/payroll/loans')
        body = resp.data.decode()
        assert emp_main.full_name in body
        assert emp_mnl.full_name not in body

    def test_create_form_renders_required_fields(
            self, client, staff_user, main_branch, login_user, db_session):
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.get('/payroll/loans/new')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'name="employee_id"' in body
        assert 'name="loan_type"' in body
        assert 'name="status"' in body
        assert 'name="principal"' in body
        assert 'name="monthly_amortization"' in body
        assert 'name="balance"' in body

    def test_edit_form_renders_conflict_snapshot_and_locked_identity(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-UI-2')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='pagibig', principal=Decimal('2400.00'),
                             monthly_amortization=Decimal('200.00'), balance=Decimal('0.00'),
                             status='paid')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.get(f'/payroll/loans/{loan.id}/edit')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Conflict-check snapshot fields (Task 12's concurrency guard).
        assert 'name="snap_status" value="paid"' in body
        assert 'name="snap_principal" value="2400.00"' in body
        assert 'name="snap_amortization" value="200.00"' in body
        assert 'name="snap_balance" value="0.00"' in body
        # Identity fields round-trip but are not a live editable <select>.
        assert f'name="employee_id" value="{emp.id}"' in body
        assert 'name="loan_type" value="pagibig"' in body

    def test_edit_form_404s_outside_accessible_branch(
            self, client, staff_user, main_branch, branch_manila, login_user, db_session):
        emp_mnl = _other_branch_employee(db_session, branch_manila, employee_no='EMP-UI-3')
        loan = EmployeeLoan(employee_id=emp_mnl.id, loan_type='sss', principal=Decimal('5000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)   # NOT branch_manila
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.get(f'/payroll/loans/{loan.id}/edit')
        assert resp.status_code == 404


class TestLoanCreate:
    def test_create_success_and_audit_logged(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-C-1')
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post('/payroll/loans/new', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '6000.00', 'monthly_amortization': '500.00', 'balance': '6000.00',
        }, follow_redirects=True)
        assert resp.status_code == 200

        loan = EmployeeLoan.query.filter_by(employee_id=emp.id, loan_type='sss').first()
        assert loan is not None
        assert loan.principal == Decimal('6000.00')
        assert loan.balance == Decimal('6000.00')
        assert loan.status == 'active'

        entry = AuditLog.query.filter_by(module='employee_loan', action='create',
                                          record_id=loan.id).first()
        assert entry is not None
        assert emp.full_name in entry.record_identifier

    def test_create_second_active_loan_same_type_is_friendly_flash_not_500(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-C-2')
        db_session.add(EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('5000'),
                                     monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                                     status='active'))
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post('/payroll/loans/new', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '3000.00', 'monthly_amortization': '300.00', 'balance': '3000.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'already has an active' in body
        assert EmployeeLoan.query.filter_by(employee_id=emp.id, loan_type='sss').count() == 1

    def test_create_two_different_loan_types_for_same_employee_is_fine(
            self, client, staff_user, main_branch, login_user, db_session):
        """A friendly duplicate-active check must not overreach: SSS and
        Pag-IBIG are independent loan_types, both allowed active at once."""
        emp = _employee(db_session, main_branch, employee_no='EMP-C-3')
        db_session.add(EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('5000'),
                                     monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                                     status='active'))
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post('/payroll/loans/new', data={
            'employee_id': str(emp.id), 'loan_type': 'pagibig', 'status': 'active',
            'principal': '2000.00', 'monthly_amortization': '200.00', 'balance': '2000.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert EmployeeLoan.query.filter_by(employee_id=emp.id, loan_type='pagibig').count() == 1

    def test_create_rejects_employee_outside_accessible_branch(
            self, client, staff_user, main_branch, branch_manila, login_user, db_session):
        emp_mnl = _other_branch_employee(db_session, branch_manila, employee_no='EMP-C-4')
        staff_user.branches.append(main_branch)   # NOT branch_manila
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post('/payroll/loans/new', data={
            'employee_id': str(emp_mnl.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '3000.00', 'monthly_amortization': '300.00', 'balance': '3000.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert EmployeeLoan.query.filter_by(employee_id=emp_mnl.id).count() == 0


class TestLoanEdit:
    def test_edit_updates_fields_and_audit_logged(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-E-1')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000.00'),
                             monthly_amortization=Decimal('500.00'), balance=Decimal('3500.00'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan.id}/edit', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '6000.00', 'monthly_amortization': '600.00', 'balance': '3000.00',
            'snap_status': 'active', 'snap_principal': '6000.00',
            'snap_amortization': '500.00', 'snap_balance': '3500.00',
        }, follow_redirects=True)
        assert resp.status_code == 200

        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.monthly_amortization == Decimal('600.00')
        assert loan2.balance == Decimal('3000.00')

        entry = AuditLog.query.filter_by(module='employee_loan', action='update',
                                          record_id=loan.id).first()
        assert entry is not None

    def test_edit_stale_snapshot_rejected_never_clobbers_a_concurrent_post(
            self, client, staff_user, main_branch, login_user, db_session):
        """MUTATION-PROOF for the concurrency guard (_claim_loan_edit): the
        submitted snap_balance does NOT match the loan's CURRENT balance --
        simulating a payroll run having posted against this loan in between
        the edit form's GET and its submit. If the implementation wrote the
        submitted balance unconditionally, this would silently overwrite the
        payroll-applied decrement -- exactly the race EmployeeLoan's docstring
        flags. The write must be rejected with a friendly flash instead."""
        emp = _employee(db_session, main_branch, employee_no='EMP-E-2')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000.00'),
                             monthly_amortization=Decimal('500.00'), balance=Decimal('3500.00'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()

        # Simulate a concurrent payroll post decrementing the balance via the
        # SAME atomic-UPDATE shape apply_loan_balances uses (not a Python
        # read/subtract/reassign) -- balance moves to 3000 underneath the
        # edit form that was already open with a snapshot of 3500.
        db.session.execute(
            db.update(EmployeeLoan).where(EmployeeLoan.id == loan.id)
            .values(balance=EmployeeLoan.balance - Decimal('500.00'))
        )
        db.session.commit()

        login_user(client, 'staff', 'staff123')
        resp = client.post(f'/payroll/loans/{loan.id}/edit', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '6000.00', 'monthly_amortization': '999.00', 'balance': '1.00',
            'snap_status': 'active', 'snap_principal': '6000.00',
            'snap_amortization': '500.00', 'snap_balance': '3500.00',   # STALE
        }, follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'changed by another user or a payroll run' in body

        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        # The stale write must NOT have applied: balance/amortization reflect
        # the concurrent post's value, never the stale form's submission.
        assert loan2.balance == Decimal('3000.00')
        assert loan2.monthly_amortization == Decimal('500.00')

    def test_edit_matching_snapshot_still_applies_normally(
            self, client, staff_user, main_branch, login_user, db_session):
        """Companion to the stale-snapshot test: proves the guard doesn't
        fail CLOSED on every edit -- an edit whose snapshot DOES match current
        DB values still applies."""
        emp = _employee(db_session, main_branch, employee_no='EMP-E-2B')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000.00'),
                             monthly_amortization=Decimal('500.00'), balance=Decimal('3500.00'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan.id}/edit', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '6000.00', 'monthly_amortization': '500.00', 'balance': '3400.00',
            'snap_status': 'active', 'snap_principal': '6000.00',
            'snap_amortization': '500.00', 'snap_balance': '3500.00',   # matches current
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.expire_all()
        loan2 = db.session.get(EmployeeLoan, loan.id)
        assert loan2.balance == Decimal('3400.00')

    def test_edit_second_active_loan_same_type_is_friendly_flash_not_500(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-E-3')
        loan1 = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('5000'),
                              monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                              status='active')
        loan2 = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('3000'),
                              monthly_amortization=Decimal('300'), balance=Decimal('0'),
                              status='paid')
        db_session.add_all([loan1, loan2])
        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        # Try to flip loan2 (currently 'paid') back to 'active' while loan1 is
        # already active for the same employee+type -- friendly flash, no 500.
        resp = client.post(f'/payroll/loans/{loan2.id}/edit', data={
            'employee_id': str(emp.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '3000.00', 'monthly_amortization': '300.00', 'balance': '0.00',
            'snap_status': 'paid', 'snap_principal': '3000.00',
            'snap_amortization': '300.00', 'snap_balance': '0.00',
        }, follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'already has another active' in body

        db.session.expire_all()
        loan2_after = db.session.get(EmployeeLoan, loan2.id)
        assert loan2_after.status == 'paid'   # unchanged

    def test_edit_404s_outside_accessible_branch(
            self, client, staff_user, main_branch, branch_manila, login_user, db_session):
        emp_mnl = _other_branch_employee(db_session, branch_manila, employee_no='EMP-E-4')
        loan = EmployeeLoan(employee_id=emp_mnl.id, loan_type='sss', principal=Decimal('5000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)   # NOT branch_manila
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan.id}/edit', data={
            'employee_id': str(emp_mnl.id), 'loan_type': 'sss', 'status': 'active',
            'principal': '9999.00', 'monthly_amortization': '999.00', 'balance': '1.00',
            'snap_status': 'active', 'snap_principal': '5000.00',
            'snap_amortization': '500.00', 'snap_balance': '5000.00',
        }, follow_redirects=True)
        assert resp.status_code == 404
        db.session.expire_all()
        untouched = db.session.get(EmployeeLoan, loan.id)
        assert untouched.balance == Decimal('5000.00')


class TestLoanDelete:
    def test_delete_with_no_payroll_history_succeeds_and_audit_logged(
            self, client, staff_user, main_branch, login_user, db_session):
        emp = _employee(db_session, main_branch, employee_no='EMP-D-1')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('5000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)
        db_session.commit()
        loan_id = loan.id
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(EmployeeLoan, loan_id) is None

        entry = AuditLog.query.filter_by(module='employee_loan', action='delete',
                                          record_id=loan_id).first()
        assert entry is not None

    def test_delete_blocked_when_referenced_by_a_payroll_run_line(
            self, client, staff_user, main_branch, login_user, db_session, run_factory):
        run = run_factory()
        emp_id = run.lines[0].employee_id
        loan = EmployeeLoan(employee_id=emp_id, loan_type='sss', principal=Decimal('5000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        db_session.commit()
        run.lines[0].calculate_amounts()   # records line.sss_loan_id = loan.id
        db_session.commit()
        assert run.lines[0].sss_loan_id == loan.id

        staff_user.branches.append(main_branch)
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan.id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'payroll history' in body
        assert db.session.get(EmployeeLoan, loan.id) is not None   # NOT deleted

    def test_delete_404s_outside_accessible_branch(
            self, client, staff_user, main_branch, branch_manila, login_user, db_session):
        emp_mnl = _other_branch_employee(db_session, branch_manila, employee_no='EMP-D-2')
        loan = EmployeeLoan(employee_id=emp_mnl.id, loan_type='sss', principal=Decimal('5000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        staff_user.branches.append(main_branch)   # NOT branch_manila
        db_session.commit()
        login_user(client, 'staff', 'staff123')

        resp = client.post(f'/payroll/loans/{loan.id}/delete', follow_redirects=True)
        assert resp.status_code == 404
        assert db.session.get(EmployeeLoan, loan.id) is not None   # NOT deleted


# ---------------------------------------------------------------------------
# Layer 6: 13th-month run -- YTD aggregation, override precedence, WHT-on-
# excess over THIRTEENTH_MONTH_EXEMPTION, and JE posting (Task 13).
# ---------------------------------------------------------------------------

def _posted_regular_run(db_session, branch, emp, run_number, basic_rate, month,
                         status='posted'):
    """A run_type='regular' run (default POSTED) with one line for `emp`,
    basic_gross driven purely by basic_rate (monthly pay_basis, no OT/
    allowances) -- used to build up an employee's YTD basic for
    service.compute_thirteenth_month. `status` is overridable so callers can
    build a draft/voided/cancelled run to prove those are EXCLUDED from the
    aggregation."""
    run = PayrollRun(
        run_number=run_number, branch_id=branch.id, run_type='regular',
        pay_frequency='monthly', period_year=2026, period_month=month, semi_period=0,
        period_start=date(2026, month, 1), period_end=date(2026, month, 28),
        pay_date=date(2026, month, 28), semi_timing='second_cutoff', status=status,
    )
    db_session.add(run)
    db_session.flush()
    line = PayrollRunLine(
        run_id=run.id, line_number=1, employee_id=emp.id,
        employee_name=emp.full_name, pay_basis='monthly', rate=basic_rate,
        tax_status_code=emp.tax_status_code, is_mwe=False,
        days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
    )
    run.lines.append(line)
    db_session.commit()
    line.calculate_amounts()
    run.calculate_totals()
    db_session.commit()
    return run


def _thirteenth_month_run(db_session, branch, run_number='PR-2026-12-9001'):
    run = PayrollRun(
        run_number=run_number, branch_id=branch.id, run_type='13th_month',
        pay_frequency='monthly', period_year=2026, period_month=12, semi_period=0,
        period_start=date(2026, 12, 1), period_end=date(2026, 12, 31),
        pay_date=date(2026, 12, 15), semi_timing='second_cutoff', status='draft',
    )
    db_session.add(run)
    db_session.commit()
    return run


def _thirteenth_month_line(db_session, run, emp, override=False, manual_amount=None):
    line = PayrollRunLine(
        run_id=run.id, line_number=len(run.lines) + 1, employee_id=emp.id,
        employee_name=emp.full_name, pay_basis=emp.pay_basis, rate=emp.basic_rate,
        tax_status_code=emp.tax_status_code, is_mwe=emp.is_minimum_wage,
        days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
        taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        thirteenth_month_override=override,
    )
    if override:
        line.thirteenth_month = manual_amount
    run.lines.append(line)
    db_session.commit()
    return line


class TestComputeThirteenthMonthAggregation:
    """service.compute_thirteenth_month(employee, year): YTD basic from
    POSTED run_type='regular' lines only, summed and / 12."""

    def test_sums_posted_regular_basics_divided_by_12(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-1')
        for m in range(1, 13):
            _posted_regular_run(db_session, main_branch, emp, f'PR-2026-{m:02d}-9101',
                                 Decimal('30000.00'), m)
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('30000.00')   # 12 * 30000 / 12

    def test_partial_year_still_divides_by_12_not_months_worked(self, db_session, main_branch):
        """Standard PH 13th-month formula divides by 12 regardless of how
        many months were actually posted -- a mid-year hire with only 6
        posted months gets HALF a month's worth, not a full month's."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-2')
        for m in range(1, 7):
            _posted_regular_run(db_session, main_branch, emp, f'PR-2026-{m:02d}-9102',
                                 Decimal('24000.00'), m)
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('12000.00')   # 6 * 24000 / 12, NOT / 6

    def test_excludes_draft_runs(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-3')
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-01-9103',
                             Decimal('30000.00'), 1)
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-02-9103',
                             Decimal('30000.00'), 2, status='draft')
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('2500.00')   # only the posted month counts: 30000/12

    def test_excludes_voided_and_cancelled_runs(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-4')
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-01-9104',
                             Decimal('30000.00'), 1)
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-02-9104',
                             Decimal('30000.00'), 2, status='voided')
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-03-9104',
                             Decimal('30000.00'), 3, status='cancelled')
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('2500.00')   # only the posted month counts

    def test_excludes_other_run_type(self, db_session, main_branch):
        """A run_type='13th_month' run's own basic (there isn't really a
        'basic_gross' concept for one, but prove the aggregation's run_type
        filter alone keeps it out regardless) never feeds the average."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-5')
        _posted_regular_run(db_session, main_branch, emp, 'PR-2026-01-9105',
                             Decimal('30000.00'), 1)
        other = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9105')
        other.status = 'posted'
        oline = _thirteenth_month_line(db_session, other, emp, override=True,
                                        manual_amount=Decimal('99999.00'))
        db_session.commit()
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('2500.00')   # 99999 from the 13th-month run never counted

    def test_excludes_other_year(self, db_session, main_branch):
        """The 2026 statutory tables are effective_from 2026-01-01 with no
        effective_to (open-ended), so a 2027 run is a valid, computable
        'other year' to prove the period_year filter -- a 2025 run would
        hit 'No SSS contribution table effective' instead, which tests a
        different thing entirely."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-6')
        run = PayrollRun(
            run_number='PR-2027-12-9106', branch_id=main_branch.id, run_type='regular',
            pay_frequency='monthly', period_year=2027, period_month=12, semi_period=0,
            period_start=date(2027, 12, 1), period_end=date(2027, 12, 31),
            pay_date=date(2027, 12, 31), semi_timing='second_cutoff', status='posted',
        )
        db_session.add(run)
        db_session.flush()
        line = PayrollRunLine(
            run_id=run.id, line_number=1, employee_id=emp.id, employee_name=emp.full_name,
            pay_basis='monthly', rate=Decimal('30000.00'), tax_status_code=emp.tax_status_code,
            is_mwe=False, days=0, hours=0, ot_pay=Decimal('0'), holiday_pay=Decimal('0'),
            taxable_allowance=Decimal('0'), nontax_allowance=Decimal('0'),
        )
        run.lines.append(line)
        db_session.commit()
        line.calculate_amounts()
        run.calculate_totals()
        db_session.commit()

        result = service.compute_thirteenth_month(emp, 2026)   # asking for 2026, not 2027
        assert result == Decimal('0.00')

    def test_no_posted_runs_at_all_is_a_clean_zero(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-7')
        result = service.compute_thirteenth_month(emp, 2026)
        assert result == Decimal('0.00')


class TestThirteenthMonthLineCalc:
    """PayrollRunLine.calculate_amounts() for run_type='13th_month':
    auto-aggregates via service.compute_thirteenth_month unless
    thirteenth_month_override is set, in which case the pre-entered
    self.thirteenth_month value wins."""

    def test_auto_aggregates_when_not_overridden(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-8')
        for m in range(1, 13):
            _posted_regular_run(db_session, main_branch, emp, f'PR-2026-{m:02d}-9108',
                                 Decimal('24000.00'), m)
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9208')
        line = _thirteenth_month_line(db_session, run, emp)
        line.calculate_amounts()

        assert line.thirteenth_month == Decimal('24000.00')
        assert line.gross_pay == Decimal('24000.00')
        assert line.basic_gross == Decimal('24000.00')

    def test_override_wins_over_auto_aggregate(self, db_session, main_branch):
        """MUTATION-PROOF for override precedence: the employee's posted-run
        history would auto-aggregate to 24,000, but this line has
        thirteenth_month_override=True with a manually-entered 50,000 already
        sitting in self.thirteenth_month BEFORE calculate_amounts() runs. If
        the implementation ignored the override flag, it would silently
        overwrite 50,000 with the auto-computed 24,000 -- this pins the
        override amount surviving the call."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-9')
        for m in range(1, 13):
            _posted_regular_run(db_session, main_branch, emp, f'PR-2026-{m:02d}-9109',
                                 Decimal('24000.00'), m)
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9209')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('50000.00'))
        line.calculate_amounts()

        assert line.thirteenth_month == Decimal('50000.00')
        assert line.gross_pay == Decimal('50000.00')

    def test_no_statutory_or_loan_amounts_on_a_13th_month_line(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-10')
        loan = EmployeeLoan(employee_id=emp.id, loan_type='sss', principal=Decimal('6000'),
                             monthly_amortization=Decimal('500'), balance=Decimal('5000'),
                             status='active')
        db_session.add(loan)
        db_session.commit()

        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9110')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('50000.00'))
        line.calculate_amounts()

        assert line.sss_ee == Decimal('0.00')
        assert line.sss_er == Decimal('0.00')
        assert line.philhealth_ee == Decimal('0.00')
        assert line.philhealth_er == Decimal('0.00')
        assert line.pagibig_ee == Decimal('0.00')
        assert line.pagibig_er == Decimal('0.00')
        # an ACTIVE sss loan exists for this employee, but a 13th-month line
        # must never draw against it.
        assert line.sss_loan == Decimal('0.00')
        assert line.sss_loan_id is None


class TestThirteenthMonthWHTBoundary:
    """WHT on a 13th-month line is computed only on the excess over
    service.THIRTEENTH_MONTH_EXEMPTION (P90,000)."""

    def test_at_exactly_90000_wht_is_zero(self, db_session, main_branch):
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-11')
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9111')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('90000.00'))
        line.calculate_amounts()

        assert line.taxable_comp == Decimal('0.00')
        assert line.wht == Decimal('0.00')
        assert line.net_pay == Decimal('90000.00')

    def test_one_centavo_over_taxes_only_the_centavo(self, db_session, main_branch):
        """MUTATION-PROOF for the >/>= boundary: 90,000.01 produces a
        taxable_comp of EXACTLY 0.01 (amount minus the exemption), not
        90,000.01 (the full amount) -- proving the implementation subtracts
        the exemption before computing taxable rather than merely gating on
        a threshold and then taxing the whole thing."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-12')
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9112')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('90000.01'))
        line.calculate_amounts()

        assert line.taxable_comp == Decimal('0.01')
        assert line.wht == Decimal('0.00')   # still inside the 0%-rate bracket 1

    def test_excess_over_90k_is_taxed_only_on_the_excess_not_the_full_amount(
            self, db_session, main_branch):
        """120,000 - 90,000 = 30,000 excess, which falls in the monthly
        bracket 2 (20,833-33,332.99 @ 15%, base 0):
        wht = 0 + (30000 - 20833) * 0.15 = 1,375.05.
        MUTATION-PROOF: if the implementation taxed the FULL 120,000 instead
        of just the excess, 120,000 falls in bracket 4 (66,667+ @ 25%, base
        8,541.80) and would produce 21,875.05 -- a wildly different number.
        Pinning the correct 1,375.05 value fails under that bug."""
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-13')
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9113')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('120000.00'))
        line.calculate_amounts()

        assert line.taxable_comp == Decimal('30000.00')
        assert line.wht == Decimal('1375.05')
        assert line.wht != Decimal('21875.05')   # what taxing the full amount would give
        assert line.net_pay == Decimal('120000.00') - Decimal('1375.05')


class TestThirteenthMonthPosting:
    """post_payroll_je(run) for a run_type='13th_month' run: only Salaries
    Expense (debit), WHT Payable (credit), and the Accrued Salaries plug
    appear -- no SSS/PhilHealth/Pag-IBIG/loan legs, since compute_line's
    generic _add_line skip-on-zero already handles it (verified, not
    assumed) -- post_payroll_je itself needed NO changes for this task."""

    def test_no_statutory_or_loan_legs_in_13th_month_je(
            self, db_session, main_branch, posted_run_factory):
        posted_run_factory()   # assigns all payroll_* control accounts
        seed_statutory_2026()
        emp = _employee(db_session, main_branch, employee_no='EMP-13-14')
        run = _thirteenth_month_run(db_session, main_branch, 'PR-2026-12-9114')
        line = _thirteenth_month_line(db_session, run, emp, override=True,
                                       manual_amount=Decimal('120000.00'))
        line.calculate_amounts()
        run.calculate_totals()
        db_session.commit()

        je = service.post_payroll_je(run)
        codes = {l.account.code for l in je.lines}
        assert codes == {'50210', '20302', '20501'}

        dr_sal = next(l for l in je.lines if l.account.code == '50210')
        assert dr_sal.debit_amount == run.total_gross == Decimal('120000.00')
        wht_line = next(l for l in je.lines if l.account.code == '20302')
        assert wht_line.credit_amount == run.total_wht == Decimal('1375.05')
        plug = next(l for l in je.lines if l.account.code == '20501')
        assert plug.credit_amount == run.total_net_pay
        assert je.is_balanced
