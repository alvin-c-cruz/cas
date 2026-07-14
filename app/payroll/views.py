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
from sqlalchemy.exc import IntegrityError

from app import db
from app.employees.models import Employee
from app.payroll import payroll_bp
from app.payroll.models import PayrollRun, PayrollRunLine, EmployeeLoan
from app.payroll.forms import PayrollRunForm, EmployeeLoanForm, ThirteenthMonthRunForm
from app.payroll import service
from app.periods.models import AccountingPeriod
from app.settings import AppSettings
from app.audit.utils import log_create, log_update, log_delete, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.users.utils import get_accessible_branches
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


# ---------------------------------------------------------------------------
# 13th-month worksheet (Task 14) -- a run_type='13th_month' PayrollRun has no
# pay-period concept (see the approved mockup, scratch/mockups/payroll-13th-
# month.html): no pay_frequency/period_start/period_end/semi_period picker,
# just Year + Pay Date. Task 13 (models.py) already wired
# PayrollRunLine.calculate_amounts() to branch on run.run_type and to honor
# thirteenth_month_override -- everything below is purely the view/template
# layer that feeds that contract; no calc-engine or model change needed here.
# ---------------------------------------------------------------------------

def _line_checked(employee_id, field):
    """True iff a checkbox input `line_<employee_id>_<field>` was present in
    the POST body. A disabled/unchecked HTML checkbox submits NOTHING, so
    request.form.get(...) returning None (or any non-'on' value) both read as
    unchecked -- there is no separate 'false' state a browser ever sends."""
    return request.form.get(f'line_{employee_id}_{field}') is not None


def _build_thirteenth_month_lines(run, employees):
    """One PayrollRunLine per employee for a run_type='13th_month' run.
    Mirrors _build_lines's identity-snapshot + append-to-run.lines shape, but
    reads the Override checkbox + manual amount instead of days/OT/holiday/
    allowance inputs (those have no meaning on a 13th-month line and are left
    at their column defaults of 0).

    The disabled-input/checkbox interaction: the worksheet template disables
    the per-line amount <input> whenever its Override checkbox is unchecked,
    and a disabled HTML input is never included in a form submission at all
    (not even as an empty string) -- so when override is NOT checked, this
    function never even looks at `line_<id>_amount`, exactly mirroring what
    the browser actually sent. When override IS checked, the amount input was
    enabled and its submitted value is read the same way any other worksheet
    cell is: through _line_decimal (fails closed to 0, never negative -- a
    13th-month amount has no meaning as negative). The amount is written onto
    line.thirteenth_month BEFORE calculate_amounts() runs, so
    PayrollRunLine._calculate_thirteenth_month_amounts() (Task 13) reads it
    back untouched per its documented override-precedence contract; when not
    overridden, thirteenth_month stays at its column default (0) and
    calculate_amounts() auto-aggregates it fresh from
    service.compute_thirteenth_month."""
    for idx, emp in enumerate(employees, start=1):
        override = _line_checked(emp.id, 'override')
        line = PayrollRunLine(
            line_number=idx,
            employee_id=emp.id,
            # Also bind the relationship object directly, not just the FK
            # scalar: calculate_amounts() -> _calculate_thirteenth_month_
            # amounts() reads self.employee (service.compute_thirteenth_month
            # needs the ORM object), and it is called on this line BEFORE
            # run/lines are ever added to a Session (mirrors the regular
            # worksheet's own build-then-add-then-commit order) -- a lazy
            # relationship load on a transient, session-less object silently
            # resolves to None instead of issuing a query, which crashed with
            # AttributeError on `employee.id` until this was added.
            employee=emp,
            employee_name=emp.full_name,
            pay_basis=emp.pay_basis or 'monthly',
            rate=emp.basic_rate or Decimal('0.00'),
            tax_status_code=emp.tax_status_code,
            is_mwe=bool(emp.is_minimum_wage),
            thirteenth_month_override=override,
        )
        if override:
            line.thirteenth_month = _line_decimal(emp.id, 'amount')
        run.lines.append(line)


def _thirteenth_month_preview(employees, year):
    """Live per-employee 13th-month calc preview for the worksheet's
    auto-fill display: the auto-aggregated YTD-basic/12 amount
    (service.compute_thirteenth_month) run through the SAME pure WHT-on-
    excess calc (service.compute_thirteenth_month_line) a saved line would
    use -- computed fresh on every render, never cached or persisted until a
    line is actually saved. This is what lets the worksheet show a live
    auto-fill even on the very first GET of a brand-new run, before any
    PayrollRunLine exists yet.

    Returns {employee_id: {'amount', 'ytd_basic', 'taxable_comp', 'wht',
    'net_pay'}}, all Decimal. 'ytd_basic' is the auto amount * 12 -- a
    display-only reconstruction of the underlying YTD sum (not a second,
    separately-queried figure), which exactly reproduces the true sum
    whenever it divides evenly by 12 (true for every case this task's tests
    build); documented here as a deliberate v1 simplification rather than
    adding a second query path into service.py for a purely informational
    column.
    """
    period_end = date(year, 12, 31)
    preview = {}
    for emp in employees:
        amount = service.compute_thirteenth_month(emp, year)
        calc = service.compute_thirteenth_month_line(amount, period_end)
        preview[emp.id] = {
            'amount': amount,
            'ytd_basic': amount * 12,
            'taxable_comp': calc['taxable_comp'],
            'wht': calc['wht'],
            'net_pay': calc['net_pay'],
        }
    return preview


def _thirteenth_month_rows(employees, lines_by_employee, preview):
    """Build the worksheet template's per-row display dict: each employee's
    SAVED line values (from the last calculate_amounts() call) if one
    already exists, else the live `preview` -- and the totals-footer dict.
    Keeping this arithmetic in Python rather than Jinja mirrors register()'s
    own totals-footer convention and keeps the sum-over-rows logic testable
    independent of template markup."""
    rows = []
    for emp in employees:
        line = lines_by_employee.get(emp.id)
        p = preview.get(emp.id, {'amount': Decimal('0.00'), 'ytd_basic': Decimal('0.00'),
                                  'taxable_comp': Decimal('0.00'), 'wht': Decimal('0.00'),
                                  'net_pay': Decimal('0.00')})
        is_override = bool(line.thirteenth_month_override) if line else False
        amount = line.thirteenth_month if line else p['amount']
        taxable_comp = line.taxable_comp if line else p['taxable_comp']
        wht = line.wht if line else p['wht']
        net_pay = line.net_pay if line else p['net_pay']
        rows.append({
            'employee': emp,
            'ytd_basic': p['ytd_basic'],
            'amount': amount,
            'is_override': is_override,
            'exempt': amount - taxable_comp,
            'taxable_comp': taxable_comp,
            'wht': wht,
            'net_pay': net_pay,
        })
    totals = {
        'count': len(rows),
        'amount': sum((r['amount'] for r in rows), Decimal('0.00')),
        'exempt': sum((r['exempt'] for r in rows), Decimal('0.00')),
        'taxable_comp': sum((r['taxable_comp'] for r in rows), Decimal('0.00')),
        'wht': sum((r['wht'] for r in rows), Decimal('0.00')),
        'net_pay': sum((r['net_pay'] for r in rows), Decimal('0.00')),
    }
    return rows, totals


def _new_thirteenth_month_run():
    """The 13th-month branch of new_run() -- see that route's own top-of-
    function run_type dispatch. Mirrors new_run's overall shape (validate ->
    period-closed check -> no-employees check -> duplicate-period check ->
    build+save -> log_create -> redirect) but against ThirteenthMonthRunForm
    and _build_thirteenth_month_lines instead of PayrollRunForm/_build_lines.
    period_month is always 12 and period_start/period_end span the full
    calendar Year field (Jan 1 - Dec 31) -- there is no user-facing period
    picker for this run type; both are derived here purely so the NOT NULL
    period_start/period_end/period_year/period_month columns (shared with the
    regular worksheet) are populated with something meaningful for a 13th-
    month run's period-uniqueness index and period-closed check."""
    form = ThirteenthMonthRunForm()
    branch_id = session.get('selected_branch_id')
    employees = _branch_employees(branch_id)
    # FlaskForm only binds formdata from the POST body, never the query
    # string, so a bare GET always falls back to the field's own default
    # (ph_now().year) regardless of a ?year= param. Honor an explicit
    # ?year= on GET (e.g. a future "New 13th-Month Run for <year>" link)
    # so the initial preview can target a specific year, not just "today".
    if request.method == 'GET':
        requested_year = request.args.get('year', type=int)
        if requested_year:
            form.year.data = requested_year
    year = form.year.data or ph_now().year
    preview = _thirteenth_month_preview(employees, year)

    def _render_form():
        rows, totals = _thirteenth_month_rows(employees, {}, preview)
        return render_template('payroll/form_13th_month.html', form=form, run=None,
                               rows=rows, totals=totals,
                               suggested_run_number=generate_payroll_run_number())

    if form.validate_on_submit():
        period_year = form.year.data
        period_month = 12

        if not _period_closed_with_flash(period_year, period_month):
            return _render_form()

        if not employees:
            flash('This branch has no active employees to include in a payroll run.', 'error')
            return _render_form()

        dup = _duplicate_period_run(branch_id, '13th_month', 'monthly',
                                     period_year, period_month, 0)
        if dup:
            flash(f'A 13th-month payroll run ({dup.run_number}) already exists for this '
                  f'branch and year. Edit that draft instead, or void it first to free the '
                  f'period.', 'error')
            return _render_form()

        try:
            run = PayrollRun(
                run_number=generate_payroll_run_number(),
                branch_id=branch_id,
                run_type='13th_month',
                pay_frequency='monthly',
                period_year=period_year,
                period_month=period_month,
                semi_period=0,
                period_start=date(period_year, 1, 1),
                period_end=date(period_year, 12, 31),
                pay_date=form.pay_date.data,
                semi_timing=None,
                status='draft',
                created_by_id=current_user.id,
            )

            _build_thirteenth_month_lines(run, employees)
            for line in run.lines:
                line.calculate_amounts()
            run.calculate_totals()

            db.session.add(run)
            commit_with_renumber_retry(run, 'run_number', generate_payroll_run_number)

            log_create(
                module='payroll_run',
                record_id=run.id,
                record_identifier=run.run_number,
                new_values=model_to_dict(run, ['run_number', 'run_type', 'period_year',
                                                'total_gross', 'total_wht', 'total_net_pay',
                                                'status'])
            )
            flash(f'13th-month payroll run "{run.run_number}" saved as draft.', 'success')
            return redirect(url_for('payroll.edit_run', id=run.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating 13th-month payroll run', exc_info=True)
            log_exception(e, severity='ERROR', module='payroll.new_run')
            flash('An unexpected error occurred while saving the payroll run. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    return _render_form()


def _edit_thirteenth_month_run(run):
    """The 13th-month branch of edit_run() -- see that route's own top-of-
    function run_type dispatch. Mirrors edit_run's shape (status guard ->
    validate -> period-closed check -> no-employees check -> duplicate-
    period check -> claim_version -> delete-and-rebuild lines -> commit) but
    against ThirteenthMonthRunForm/_build_thirteenth_month_lines."""
    if run.status != 'draft':
        flash('Only draft payroll runs can be edited.', 'error')
        return redirect(url_for('payroll.register'))

    branch_id = session.get('selected_branch_id')
    employees = _branch_employees(branch_id)
    form = ThirteenthMonthRunForm(obj=run)
    if request.method == 'GET':
        form.year.data = run.period_year
        form.pay_date.data = run.pay_date

    year = form.year.data or run.period_year
    preview = _thirteenth_month_preview(employees, year)

    def _render_edit_form():
        lines_by_employee = {l.employee_id: l for l in run.lines} if request.method == 'GET' else {}
        rows, totals = _thirteenth_month_rows(employees, lines_by_employee, preview)
        return render_template('payroll/form_13th_month.html', form=form, run=run,
                               rows=rows, totals=totals, suggested_run_number=run.run_number)

    if form.validate_on_submit():
        period_year = form.year.data
        period_month = 12

        if not _period_closed_with_flash(period_year, period_month):
            return _render_edit_form()

        if not employees:
            flash('This branch has no active employees to include in a payroll run.', 'error')
            return _render_edit_form()

        dup = _duplicate_period_run(branch_id, '13th_month', 'monthly',
                                     period_year, period_month, 0, exclude_run_id=run.id)
        if dup:
            flash(f'A 13th-month payroll run ({dup.run_number}) already exists for this '
                  f'branch and year.', 'error')
            return _render_edit_form()

        try:
            if not claim_version(PayrollRun, run.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('payroll_run', run.id), 'error')
                return _render_edit_form()

            run.period_year = period_year
            run.period_month = period_month
            run.period_start = date(period_year, 1, 1)
            run.period_end = date(period_year, 12, 31)
            run.pay_date = form.pay_date.data

            # Delete and rebuild the lines -- mirrors edit_run's own
            # replace-all convention.
            for old_line in list(run.lines):
                db.session.delete(old_line)
            run.lines = []
            db.session.flush()

            _build_thirteenth_month_lines(run, employees)
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
            flash(f'13th-month payroll run "{run.run_number}" updated.', 'success')
            return redirect(url_for('payroll.edit_run', id=run.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error editing 13th-month payroll run', exc_info=True)
            log_exception(e, severity='ERROR', module='payroll.edit_run')
            flash('An unexpected error occurred while updating the payroll run. Please try '
                  'again; if it persists, contact your administrator.', 'error')

    return _render_edit_form()


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
    # Task 14: dispatch to the genuinely separate 13th-month worksheet
    # path. On GET the choice comes from a query param (the register page's
    # "+ Enter 13th-Month Run" link); on POST it comes from the submitted
    # run_type field the 13th-month template itself carries as a fixed
    # hidden value -- never a user-editable <select> on that form (see
    # ThirteenthMonthRunForm's docstring). The plain regular-worksheet path
    # below is completely untouched for run_type == 'regular' (the default
    # when the param/field is absent), preserving Task 8/9's approved flow.
    run_type = (request.form.get('run_type') if request.method == 'POST'
                else request.args.get('run_type')) or 'regular'
    if run_type == '13th_month':
        return _new_thirteenth_month_run()

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
    # Task 14: dispatch on the run's OWN persisted run_type -- unlike
    # new_run (where nothing is saved yet, so the choice comes from a
    # query param/form field), an existing run's type is authoritative and
    # immutable through this route.
    if run.run_type == '13th_month':
        return _edit_thirteenth_month_run(run)
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


# ---------------------------------------------------------------------------
# Employee Loan editor (Task 12) -- CRUD for EmployeeLoan, the master record a
# payroll line's calculate_amounts() (see models.py) looks up to deduct
# min(monthly_amortization, balance). Branch-scoped through employee.branch_id
# (EmployeeLoan has no branch_id of its own) against the CURRENT USER's full
# set of ACCESSIBLE branches -- mirrors app/withholding_certificates/views.py's
# _accessible_branch_ids() idiom, not payroll's own single-selected-branch
# register() (the brief calls for "accessible branches", plural).
# ---------------------------------------------------------------------------

_LOAN_FIELDS = ['employee_id', 'loan_type', 'status', 'principal',
                'monthly_amortization', 'balance']


def _accessible_branch_ids():
    return [b.id for b in get_accessible_branches(current_user)]


def _loan_or_404(loan_id):
    loan = db.get_or_404(EmployeeLoan, loan_id)
    if not current_user.has_full_access and loan.employee.branch_id not in _accessible_branch_ids():
        abort(404)
    return loan


def _set_loan_choices(form, current_employee=None):
    """Employee picker choices: active employees in the current user's
    accessible branches. `current_employee` (edit mode) is force-included even
    if since deactivated or moved out of an accessible branch, so an existing
    loan's employee_id round-trips through the hidden field on edit without
    ever failing SelectField's "not a valid choice" validation."""
    q = Employee.query.filter_by(is_active=True)
    if not current_user.has_full_access:
        q = q.filter(Employee.branch_id.in_(_accessible_branch_ids()))
    employees = q.order_by(Employee.employee_no).all()
    if current_employee is not None and current_employee.id not in {e.id for e in employees}:
        employees = [current_employee] + employees
    # ": " code-name separator -- matches this codebase's established
    # Choices.js dropdown convention (feedback-dropdown-colon-separator), not
    # an invented em-dash format.
    form.employee_id.choices = [(e.id, f'{e.employee_no}: {e.full_name}') for e in employees]


def _active_loan_conflict(employee_id, loan_type, exclude_loan_id=None):
    """An existing ACTIVE loan of the same employee+type -- return it, or None.
    Mirrors _duplicate_period_run's pre-check-before-insert idiom: the DB's
    partial unique index (uq_employee_loan_active_per_type) remains the hard
    backstop for a genuine race, but this turns the common case into a clean
    flash instead of a raw IntegrityError reaching the user."""
    q = EmployeeLoan.query.filter_by(
        employee_id=employee_id, loan_type=loan_type, status='active')
    if exclude_loan_id is not None:
        q = q.filter(EmployeeLoan.id != exclude_loan_id)
    return q.first()


def _loan_snapshot_from_form():
    """Read the loan_form.html edit template's snap_* hidden inputs (the
    principal/monthly_amortization/balance/status values that were current
    when the GET rendered the form) straight from the raw POST body -- same
    "never trust form.<field>.data for a conflict check, read request.form
    directly" discipline as concurrency.submitted_version(), and for the same
    reason: WTForms falls back to the obj value for an absent/malformed field,
    which would make a dropped snapshot silently pass as "unchanged".
    Fails closed to None (caller treats that as a conflict, not a bypass)."""
    def _dec(name):
        raw = request.form.get(name)
        if raw is None:
            return None
        try:
            return Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            return None

    status = request.form.get('snap_status')
    principal = _dec('snap_principal')
    amortization = _dec('snap_amortization')
    balance = _dec('snap_balance')
    if not status or principal is None or amortization is None or balance is None:
        return None
    return {'status': status, 'principal': principal,
            'monthly_amortization': amortization, 'balance': balance}


def _claim_loan_edit(loan_id, snapshot, new_values):
    """Atomically apply `new_values` to EmployeeLoan `loan_id`, but ONLY if its
    status/principal/monthly_amortization/balance still match `snapshot` --
    a single conditional SQL UPDATE (WHERE ... AND col = snapshot_val ...),
    same "let the database be the arbiter, never read-then-compare in Python"
    reasoning as concurrency.claim_version. Returns True (write applied) or
    False (someone else changed one of these columns since the edit form's
    GET -- caller re-renders with a fresh read + friendly flash).

    THE CONCURRENCY DECISION (EmployeeLoan.__doc__'s open question, Task 12):
    this task does NOT add RowVersioned to EmployeeLoan. A bare RowVersioned +
    claim_version mirror of PayrollRun's edit_run would only guard THIS
    route's own writes against ANOTHER concurrent call to this same route --
    it would NOT catch a race against service.apply_loan_balances/
    restore_loan_balances (post_run/cancel_run), because those functions
    mutate `balance` via their own raw Core UPDATE (an atomic SQL-side
    balance +/- amount) that does not touch a row_version counter, and this
    task is explicitly barred from editing them. So a plain row_version guard
    here would be theater for the exact race the docstring flags: an
    accountant's edit-form submit racing a payroll post/cancel on the SAME
    loan's `balance`.

    Instead, this function guards the SPECIFIC columns both write paths
    actually touch (principal/monthly_amortization/balance/status) via a
    compare-and-swap keyed on the values this route itself read at GET time --
    no schema change, no migration, and it closes BOTH races that matter:
    two humans editing the same loan concurrently, AND this edit racing a
    payroll post/cancel's atomic balance mutation (since `balance` is one of
    the guarded columns, an intervening post/cancel changes it and the WHERE
    clause below simply matches zero rows). The trade-off against a "real"
    RowVersioned column: this is bespoke to this one route rather than the
    codebase's shared claim_version primitive, and a THIRD future mutator of
    these columns would need to be folded into the same WHERE-clause
    discipline by hand rather than "just bump row_version". Judged
    acceptable because EmployeeLoan currently has exactly two write paths
    (this route, and apply_loan_balances/restore_loan_balances via `balance`
    only) and this guard already covers both.
    """
    result = db.session.execute(
        db.update(EmployeeLoan)
        .where(EmployeeLoan.id == loan_id,
               EmployeeLoan.status == snapshot['status'],
               EmployeeLoan.principal == snapshot['principal'],
               EmployeeLoan.monthly_amortization == snapshot['monthly_amortization'],
               EmployeeLoan.balance == snapshot['balance'])
        .values(**new_values, updated_at=ph_now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


@payroll_bp.route('/payroll/loans')
@login_required
def list_loans():
    q = EmployeeLoan.query.join(Employee, EmployeeLoan.employee_id == Employee.id)
    if not current_user.has_full_access:
        q = q.filter(Employee.branch_id.in_(_accessible_branch_ids()))
    loans = q.order_by(EmployeeLoan.id.desc()).all()
    return render_template('payroll/loans_list.html', loans=loans)


@payroll_bp.route('/payroll/loans/new', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def new_loan():
    form = EmployeeLoanForm()
    _set_loan_choices(form)

    if form.validate_on_submit():
        conflict = None
        if form.status.data == 'active':
            conflict = _active_loan_conflict(form.employee_id.data, form.loan_type.data)
        if conflict:
            emp = db.session.get(Employee, form.employee_id.data)
            flash(f'{emp.full_name if emp else "This employee"} already has an active '
                  f'{form.loan_type.data.upper()} loan. Edit that loan instead, or set it '
                  f'to Paid/Cancelled before adding a new one.', 'error')
            return render_template('payroll/loan_form.html', form=form, loan=None)

        loan = EmployeeLoan(
            employee_id=form.employee_id.data,
            loan_type=form.loan_type.data,
            status=form.status.data,
            principal=form.principal.data,
            monthly_amortization=form.monthly_amortization.data,
            balance=form.balance.data,
        )
        try:
            db.session.add(loan)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('That employee already has an active loan of this type (added by another '
                  'user just now). Please reload and try again.', 'error')
            return render_template('payroll/loan_form.html', form=form, loan=None)

        log_create(
            module='employee_loan', record_id=loan.id,
            record_identifier=f'{loan.employee.full_name} — {loan.loan_type.upper()}',
            new_values=model_to_dict(loan, _LOAN_FIELDS),
        )
        flash('Loan recorded.', 'success')
        return redirect(url_for('payroll.list_loans'))

    return render_template('payroll/loan_form.html', form=form, loan=None)


@payroll_bp.route('/payroll/loans/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit_loan(id):
    loan = _loan_or_404(id)
    form = EmployeeLoanForm(obj=loan)
    _set_loan_choices(form, current_employee=loan.employee)
    if request.method == 'GET':
        form.employee_id.data = loan.employee_id

    if form.validate_on_submit():
        snapshot = _loan_snapshot_from_form()
        if snapshot is None:
            flash('This page is missing conflict-check data; please reload and try again.',
                  'error')
            return render_template('payroll/loan_form.html', form=form, loan=loan)

        if form.status.data == 'active':
            conflict = _active_loan_conflict(loan.employee_id, loan.loan_type,
                                             exclude_loan_id=loan.id)
            if conflict:
                flash(f'{loan.employee.full_name} already has another active '
                      f'{loan.loan_type.upper()} loan. Only one active loan per type is '
                      f'allowed.', 'error')
                return render_template('payroll/loan_form.html', form=form, loan=loan)

        old_values = model_to_dict(loan, _LOAN_FIELDS)
        new_values = {
            'status': form.status.data,
            'principal': form.principal.data,
            'monthly_amortization': form.monthly_amortization.data,
            'balance': form.balance.data,
        }
        try:
            applied = _claim_loan_edit(loan.id, snapshot, new_values)
        except IntegrityError:
            db.session.rollback()
            flash(f'{loan.employee.full_name} already has another active '
                  f'{loan.loan_type.upper()} loan (set by another user just now). Reload '
                  f'and try again.', 'error')
            return redirect(url_for('payroll.edit_loan', id=loan.id))

        if not applied:
            db.session.rollback()
            flash('This loan was changed by another user or a payroll run since you opened '
                  'this page (e.g. a run was posted or cancelled, changing the balance). '
                  'Reload the page to see the current values and try again.', 'error')
            return redirect(url_for('payroll.edit_loan', id=loan.id))

        db.session.commit()
        log_update(
            module='employee_loan', record_id=loan.id,
            record_identifier=f'{loan.employee.full_name} — {loan.loan_type.upper()}',
            old_values=old_values,
            new_values={k: str(v) for k, v in new_values.items()},
        )
        flash('Loan updated.', 'success')
        return redirect(url_for('payroll.list_loans'))

    return render_template('payroll/loan_form.html', form=form, loan=loan)


@payroll_bp.route('/payroll/loans/<int:id>/delete', methods=['POST'])
@login_required
@staff_or_above_required
def delete_loan(id):
    """No-JS-popup delete (custom HTML modal on the list page). Blocked when
    the loan has payroll history -- referenced by any PayrollRunLine's
    sss_loan_id/pagibig_loan_id (plain Integer FKs, no ORM cascade -- SQLite
    FK enforcement is off app-wide, so a delete here would otherwise leave a
    dangling reference a later report/lookup silently treats as "no loan").
    A loan with history should be set to Cancelled instead, never deleted."""
    loan = _loan_or_404(id)
    referenced = PayrollRunLine.query.filter(
        db.or_(PayrollRunLine.sss_loan_id == loan.id, PayrollRunLine.pagibig_loan_id == loan.id)
    ).first()
    if referenced:
        flash('This loan has payroll history (used on at least one payroll run) and cannot '
              'be deleted. Set its status to Cancelled instead.', 'error')
        return redirect(url_for('payroll.list_loans'))

    old_values = model_to_dict(loan, _LOAN_FIELDS)
    identifier = f'{loan.employee.full_name} — {loan.loan_type.upper()}'
    db.session.delete(loan)
    db.session.commit()
    log_delete(module='employee_loan', record_id=id, record_identifier=identifier,
              old_values=old_values)
    flash('Loan deleted.', 'success')
    return redirect(url_for('payroll.list_loans'))
