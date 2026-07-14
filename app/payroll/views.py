"""Payroll Worksheet: draft PayrollRun create/edit/list.

Mirrors app/cash_disbursements/views.py's document CRUD idiom (role-gate
decorator, before_request branch guard, delete-and-rebuild lines on edit,
optimistic-lock via claim_version/submitted_version, audit log on every
write). This slice does NOT post a journal entry -- post_payroll_je (Task 7)
is wired to a view in Task 10.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import render_template, redirect, url_for, flash, request, session, abort, current_app
from flask_login import login_required, current_user

from app import db
from app.employees.models import Employee
from app.payroll import payroll_bp
from app.payroll.models import PayrollRun, PayrollRunLine
from app.payroll.forms import PayrollRunForm
from app.payroll import service
from app.periods.models import AccountingPeriod
from app.settings import AppSettings
from app.audit.utils import log_create, log_update, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.concurrency import (claim_version, conflict_message, submitted_version,
                                    commit_with_renumber_retry)


def staff_or_above_required(f):
    """Staff, Accountant, Chief Accountant, and Admin may create/edit a draft
    worksheet, or void it (mirrors CDV's staff_or_above_required)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ('staff', 'accountant', 'admin', 'chief_accountant'):
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def accountant_or_admin_required(f):
    """Only Accountants and full-access users (Admin/Chief Accountant, via
    has_full_access) may post or cancel a payroll run -- mirrors CDV's
    accountant_or_admin_required exactly."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@payroll_bp.before_request
def require_branch_selection():
    if current_user.is_authenticated and not session.get('selected_branch_id'):
        flash('Please select a branch to continue.', 'warning')
        return redirect(url_for('users.select_branch'))


def generate_payroll_run_number():
    """Next PR-YYYY-MM-NNNN, a company-wide sequence that resets each month.

    Orders candidate rows by PayrollRun.id.desc() (insertion order) rather than
    a lexicographic sort on the run_number string -- CLAUDE.md's
    document-numbering-system convention flags string .desc() on a
    PREFIX-YYYY-MM-NNNN column as a landmine (it silently breaks once the
    numeric suffix crosses a digit-width boundary, e.g. "0999" sorting after
    "1000"). Takes the numeric MAX of every parsed suffix among this month's
    rows -- not just the single latest-inserted row's number -- so a
    concurrently-retried or out-of-order id can never yield a stale or
    duplicate suggestion.
    """
    now = ph_now()
    prefix = f'PR-{now.year}-{now.month:02d}-'
    rows = PayrollRun.query.filter(
        PayrollRun.run_number.like(f'{prefix}%')
    ).order_by(PayrollRun.id.desc()).all()
    suffixes = []
    for r in rows:
        try:
            suffixes.append(int(r.run_number.split('-')[-1]))
        except (ValueError, IndexError):
            continue
    next_num = (max(suffixes) + 1) if suffixes else 1
    return f'{prefix}{next_num:04d}'


def _get_run_or_404(id):
    run = db.get_or_404(PayrollRun, id)
    if run.branch_id != session.get('selected_branch_id'):
        abort(404)
    return run


def _branch_employees(branch_id):
    """Active employees for the current branch, in a stable display order.
    The single source of truth for "which employees belong on this worksheet"
    -- read fresh at both GET (to render rows) and POST (to know which
    line_<id>_* keys to trust), never from client-submitted employee ids."""
    return Employee.query.filter_by(branch_id=branch_id, is_active=True).order_by(
        Employee.employee_no).all()


def _period_closed_with_flash(period_year, period_month):
    """Friendly flash + False if the run's period is closed; True (proceed) otherwise.
    AccountingPeriod.is_period_closed(year, month) is the canonical check (see
    app/periods/models.py) -- no existing posting view called it before this task."""
    if AccountingPeriod.is_period_closed(period_year, period_month):
        from datetime import date as _date
        period_name = _date(period_year, period_month, 1).strftime('%B %Y')
        flash(f'Cannot save a payroll run for {period_name} -- this accounting '
              f'period has been closed.', 'error')
        return False
    return True


def _duplicate_period_run(branch_id, run_type, pay_frequency, period_year,
                           period_month, semi_period, exclude_run_id=None):
    """An existing NON-voided/cancelled run already occupies this exact period
    key (mirrors the DB partial-unique index from Task 6) -- return it, or
    None. Checked here so a collision surfaces as a clean flash instead of a
    raw IntegrityError; the DB index remains the hard backstop for a genuine race."""
    q = PayrollRun.query.filter(
        PayrollRun.branch_id == branch_id,
        PayrollRun.run_type == run_type,
        PayrollRun.pay_frequency == pay_frequency,
        PayrollRun.period_year == period_year,
        PayrollRun.period_month == period_month,
        PayrollRun.semi_period == semi_period,
        PayrollRun.status.notin_(('voided', 'cancelled')),
    )
    if exclude_run_id is not None:
        q = q.filter(PayrollRun.id != exclude_run_id)
    return q.first()


def _line_decimal(employee_id, field):
    """Read one entered-input cell for `employee_id` from request.form. Fails
    closed to 0 on missing/invalid input; never negative (a negative entered
    amount has no meaning for days/OT/holiday/allowances)."""
    raw = request.form.get(f'line_{employee_id}_{field}', '0')
    try:
        val = Decimal(str(raw).strip() or '0')
    except (InvalidOperation, ValueError):
        val = Decimal('0')
    if val < 0:
        val = Decimal('0')
    return val


def _build_lines(run, employees):
    """Build one PayrollRunLine per employee, snapshotting identity/rate
    fields from Employee and reading entered inputs from the submitted form.
    Appends each line onto run.lines (sets up the ORM relationship so
    line.calculate_amounts() can read run.pay_frequency/period_end/etc. even
    before the run is flushed)."""
    for idx, emp in enumerate(employees, start=1):
        line = PayrollRunLine(
            line_number=idx,
            employee_id=emp.id,
            employee_name=emp.full_name,
            pay_basis=emp.pay_basis or 'monthly',
            rate=emp.basic_rate or Decimal('0.00'),
            tax_status_code=emp.tax_status_code,
            is_mwe=bool(emp.is_minimum_wage),
            days=_line_decimal(emp.id, 'days'),
            hours=_line_decimal(emp.id, 'hours'),
            ot_pay=_line_decimal(emp.id, 'ot_pay'),
            holiday_pay=_line_decimal(emp.id, 'holiday_pay'),
            taxable_allowance=_line_decimal(emp.id, 'taxable_allowance'),
            nontax_allowance=_line_decimal(emp.id, 'nontax_allowance'),
        )
        run.lines.append(line)


def _semi_timing_for(pay_frequency):
    """Snapshot of the payroll_semi_monthly_timing setting -- only meaningful
    for a semi-monthly run; every other frequency stores None (compute_line's
    _semi_applies_statutory short-circuits to True when freq != 'semi_monthly',
    never reading this value)."""
    if pay_frequency != 'semi_monthly':
        return None
    return AppSettings.get_setting('payroll_semi_monthly_timing', 'second_cutoff')


# A voided or cancelled run's monetary figures are excluded from the
# register's totals footer AND rendered as a placeholder ('--') on the row
# itself -- mirrors _duplicate_period_run's status.notin_(...) (both statuses
# free the period slot, so neither is a "real" contributor to reported sums).
_REGISTER_EXCLUDED_STATUSES = ('voided', 'cancelled')


@payroll_bp.route('/payroll/runs')
@login_required
def register():
    branch_id = session.get('selected_branch_id')
    runs = (PayrollRun.query.filter_by(branch_id=branch_id)
            .order_by(PayrollRun.id.desc()).all())

    countable = [r for r in runs if r.status not in _REGISTER_EXCLUDED_STATUSES]
    totals_gross = sum((r.total_gross for r in countable), Decimal('0.00'))
    totals_net_pay = sum((r.total_net_pay for r in countable), Decimal('0.00'))
    totals = {
        'count': len(countable),
        'gross': totals_gross,
        'net_pay': totals_net_pay,
        'deductions': totals_gross - totals_net_pay,
    }

    return render_template('payroll/register.html', runs=runs, totals=totals,
                           excluded_statuses=_REGISTER_EXCLUDED_STATUSES)


@payroll_bp.route('/payroll/runs/<int:id>')
@login_required
def view_run(id):
    run = _get_run_or_404(id)
    preview = service.build_je_preview(run)
    return render_template('payroll/detail.html', run=run, preview=preview, now=ph_now())


@payroll_bp.route('/payroll/runs/new', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def new_run():
    form = PayrollRunForm()
    branch_id = session.get('selected_branch_id')
    employees = _branch_employees(branch_id)

    def _render_form():
        return render_template('payroll/form.html', form=form, run=None,
                               employees=employees, lines_by_employee={},
                               suggested_run_number=generate_payroll_run_number())

    if form.validate_on_submit():
        period_year = form.period_start.data.year
        period_month = form.period_start.data.month
        semi_period = int(form.semi_period.data or 0)

        if not _period_closed_with_flash(period_year, period_month):
            return _render_form()

        if not employees:
            flash('This branch has no active employees to include in a payroll run.', 'error')
            return _render_form()

        dup = _duplicate_period_run(branch_id, form.run_type.data, form.pay_frequency.data,
                                     period_year, period_month, semi_period)
        if dup:
            flash(f'A payroll run ({dup.run_number}) already exists for this branch, '
                  f'run type, frequency, and period. Edit that draft instead, or void it '
                  f'first to free the period.', 'error')
            return _render_form()

        try:
            run = PayrollRun(
                run_number=generate_payroll_run_number(),
                branch_id=branch_id,
                run_type=form.run_type.data,
                pay_frequency=form.pay_frequency.data,
                period_year=period_year,
                period_month=period_month,
                semi_period=semi_period,
                period_start=form.period_start.data,
                period_end=form.period_end.data,
                pay_date=form.pay_date.data,
                semi_timing=_semi_timing_for(form.pay_frequency.data),
                status='draft',
                created_by_id=current_user.id,
            )

            _build_lines(run, employees)
            for line in run.lines:
                line.calculate_amounts()
            run.calculate_totals()

            db.session.add(run)
            commit_with_renumber_retry(run, 'run_number', generate_payroll_run_number)

            log_create(
                module='payroll_run',
                record_id=run.id,
                record_identifier=run.run_number,
                new_values=model_to_dict(run, ['run_number', 'run_type', 'pay_frequency',
                                                'period_year', 'period_month', 'total_gross',
                                                'total_net_pay', 'status'])
            )
            flash(f'Payroll run "{run.run_number}" saved as draft.', 'success')
            return redirect(url_for('payroll.edit_run', id=run.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating payroll run', exc_info=True)
            log_exception(e, severity='ERROR', module='payroll.new_run')
            flash('An unexpected error occurred while saving the payroll run. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    return _render_form()


@payroll_bp.route('/payroll/runs/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit_run(id):
    run = _get_run_or_404(id)
    if run.status != 'draft':
        flash('Only draft payroll runs can be edited.', 'error')
        return redirect(url_for('payroll.register'))

    branch_id = session.get('selected_branch_id')
    employees = _branch_employees(branch_id)
    form = PayrollRunForm(obj=run)
    if request.method == 'GET':
        form.semi_period.data = str(run.semi_period)

    def _render_edit_form():
        lines_by_employee = {l.employee_id: l for l in run.lines} if request.method == 'GET' else {}
        return render_template('payroll/form.html', form=form, run=run,
                               employees=employees, lines_by_employee=lines_by_employee,
                               suggested_run_number=run.run_number)

    if form.validate_on_submit():
        period_year = form.period_start.data.year
        period_month = form.period_start.data.month
        semi_period = int(form.semi_period.data or 0)

        if not _period_closed_with_flash(period_year, period_month):
            return _render_edit_form()

        if not employees:
            flash('This branch has no active employees to include in a payroll run.', 'error')
            return _render_edit_form()

        dup = _duplicate_period_run(branch_id, form.run_type.data, form.pay_frequency.data,
                                     period_year, period_month, semi_period,
                                     exclude_run_id=run.id)
        if dup:
            flash(f'A payroll run ({dup.run_number}) already exists for this branch, '
                  f'run type, frequency, and period.', 'error')
            return _render_edit_form()

        try:
            if not claim_version(PayrollRun, run.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('payroll_run', run.id), 'error')
                return _render_edit_form()

            run.run_type = form.run_type.data
            run.pay_frequency = form.pay_frequency.data
            run.period_year = period_year
            run.period_month = period_month
            run.semi_period = semi_period
            run.period_start = form.period_start.data
            run.period_end = form.period_end.data
            run.pay_date = form.pay_date.data
            run.semi_timing = _semi_timing_for(form.pay_frequency.data)

            # Delete and rebuild the lines (mirrors CDV/AP/CRV edit's
            # replace-all convention) -- the branch employee roster is
            # re-read fresh above, so a hire/deactivation since this draft
            # was created is picked up rather than silently ignored.
            for old_line in list(run.lines):
                db.session.delete(old_line)
            run.lines = []
            db.session.flush()

            _build_lines(run, employees)
            for line in run.lines:
                line.calculate_amounts()
            run.calculate_totals()

            db.session.commit()

            log_update(
                module='payroll_run',
                record_id=run.id,
                record_identifier=run.run_number,
                old_values={}, new_values={}
            )
            flash(f'Payroll run "{run.run_number}" updated.', 'success')
            return redirect(url_for('payroll.edit_run', id=run.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error editing payroll run', exc_info=True)
            log_exception(e, severity='ERROR', module='payroll.edit_run')
            flash('An unexpected error occurred while updating the payroll run. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    return _render_edit_form()


@payroll_bp.route('/payroll/runs/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post_run(id):
    """Post a draft payroll run: build the accrual JE (service.post_payroll_je)
    and flip the run to 'posted'. Mirrors CDV's post() route, with two
    payroll-specific additions the brief calls out: the period-lock check
    (Task 8's _period_closed_with_flash, not CDV's date-based helper) and a
    real claim_version optimistic-lock (CDV's own post() route does not need
    one -- it has no editable fields between GET and POST -- but a payroll
    run's draft can be edited right up to the post click, so the same
    lost-update race edit_run() already guards against applies here too)."""
    run = _get_run_or_404(id)
    if run.status != 'draft':
        flash('Only draft payroll runs can be posted.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    if not _period_closed_with_flash(run.period_year, run.period_month):
        return redirect(url_for('payroll.view_run', id=id))
    try:
        if not claim_version(PayrollRun, run.id, submitted_version()):
            db.session.rollback()
            flash(conflict_message('payroll_run', run.id), 'error')
            return redirect(url_for('payroll.view_run', id=id))

        # post_payroll_je reads run.status/posted_by_id/posted_at to decide
        # the JE's own status/actor/timestamp -- set them on the run FIRST.
        run.status = 'posted'
        run.posted_by_id = current_user.id
        run.posted_at = ph_now()

        je = service.post_payroll_je(run)
        run.journal_entry_id = je.id
        # Task 11: decrement each line's referenced EmployeeLoan.balance by the
        # amount that line actually applied (already min(amortization, balance)
        # capped by compute_line). Inside the SAME claim_version-locked
        # transaction as everything else above -- see
        # service.apply_loan_balances's docstring for the atomic-UPDATE
        # reasoning and its documented concurrent-race gap.
        service.apply_loan_balances(run)
        db.session.commit()

        log_audit(
            module='payroll_run', action='post',
            record_id=run.id,
            record_identifier=run.run_number,
            notes=f'Posted by {current_user.username}'
        )
        flash(f'Payroll run "{run.run_number}" posted successfully!', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting payroll run', exc_info=True)
        log_exception(e, severity='ERROR', module='payroll.post_run')
        flash('An unexpected error occurred while posting the payroll run. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('payroll.view_run', id=id))


@payroll_bp.route('/payroll/runs/<int:id>/void', methods=['POST'])
@login_required
@staff_or_above_required
def void_run(id):
    """Void a draft payroll run. Mirrors CDV's void() route: defensively
    deletes a linked JE if one exists (a draft run should never actually have
    one in this codebase's flow -- post_payroll_je only ever runs from
    post_run, which requires draft status in the first place -- but the
    defensive delete costs nothing and mirrors CDV's own shape exactly)."""
    run = _get_run_or_404(id)
    if run.status != 'draft':
        flash('Only draft payroll runs can be voided.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    # Task 11: deliberately NOT calling service.restore_loan_balances(run)
    # here. Unlike the defensive JE-delete just below (harmless because a
    # draft never actually carries a real JE), a draft's lines DO carry
    # computed sss_loan/pagibig_loan PREVIEW amounts (calculate_amounts()
    # recomputes them on every draft save) even though apply_loan_balances()
    # was never called for this run (it only ever runs from post_run, which
    # requires draft status to even start). Calling restore here would
    # incorrectly credit a loan balance that was never debited. See
    # service.restore_loan_balances's docstring.
    void_reason = request.form.get('void_reason', '').strip()
    if len(void_reason) < 10:
        flash('Void reason must be at least 10 characters.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    try:
        if run.journal_entry_id:
            from app.journal_entries.models import JournalEntry as _JE
            je_to_delete = db.session.get(_JE, run.journal_entry_id)
            if je_to_delete:
                db.session.delete(je_to_delete)
            run.journal_entry_id = None
            run.journal_entry = None
        run.status = 'voided'
        run.voided_at = ph_now()
        run.voided_by_id = current_user.id
        run.void_reason = void_reason
        db.session.commit()
        log_audit(
            module='payroll_run', action='void',
            record_id=run.id,
            record_identifier=run.run_number,
            notes=f'Voided by {current_user.username}. Reason: {void_reason}'
        )
        flash(f'Payroll run "{run.run_number}" voided.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error voiding payroll run', exc_info=True)
        log_exception(e, severity='ERROR', module='payroll.void_run')
        flash('An unexpected error occurred while voiding the payroll run. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('payroll.view_run', id=id))


@payroll_bp.route('/payroll/runs/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel_run(id):
    """Cancel a posted payroll run: post a Dr<->Cr swapped reversal JE
    (service.build_payroll_reversal_je) dated `reversal_date`, then flip the
    run to 'cancelled'. Mirrors CDV's cancel() route. The reversal's OWN
    posting-date period must be open -- reused via the same payroll-specific
    _period_closed_with_flash(year, month) check post_run uses (not CDV's
    date-based validate_transaction_date_with_flash), so both lifecycle
    writes share one period-lock idiom in this module."""
    run = _get_run_or_404(id)
    if run.status != 'posted':
        flash('Only posted payroll runs can be cancelled.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Cancellation reason must be at least 10 characters.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    reversal_date_str = request.form.get('reversal_date', '')
    try:
        reversal_date = date.fromisoformat(reversal_date_str)
    except ValueError:
        flash('Invalid reversal date.', 'error')
        return redirect(url_for('payroll.view_run', id=id))
    if not _period_closed_with_flash(reversal_date.year, reversal_date.month):
        return redirect(url_for('payroll.view_run', id=id))
    try:
        service.build_payroll_reversal_je(run, reversal_date, current_user.id)
        # Task 11: restore each line's referenced EmployeeLoan.balance by the
        # EXACT amount apply_loan_balances() decremented at post -- see
        # service.restore_loan_balances's docstring for why this must use the
        # amount stored on the line, never a fresh recompute.
        service.restore_loan_balances(run)
        run.status = 'cancelled'
        run.cancelled_at = ph_now()
        run.cancel_reason = cancel_reason
        db.session.commit()
        log_audit(
            module='payroll_run', action='cancel',
            record_id=run.id,
            record_identifier=run.run_number,
            notes=f'Cancelled by {current_user.username}. Reason: {cancel_reason}'
        )
        flash(f'Payroll run "{run.run_number}" cancelled. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling payroll run', exc_info=True)
        log_exception(e, severity='ERROR', module='payroll.cancel_run')
        flash('An unexpected error occurred while cancelling the payroll run. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('payroll.view_run', id=id))
