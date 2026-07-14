"""Form for the Payroll Worksheet: draft PayrollRun header (create/edit).

Per-employee entered inputs (days/hours/OT/holiday/allowances) are deliberately
NOT modeled as a WTForms FieldList/FormField -- there is no existing precedent
for that pattern anywhere in this codebase (grep confirms zero uses), and a
FieldList's positional indices are fragile against the branch's employee
roster changing between the GET that renders the worksheet and the POST that
submits it (an employee hired, deactivated, or reordered mid-edit would desync
index N from the employee row it was rendered for). Instead the worksheet
template renders one row per CURRENT branch employee with inputs keyed by
`line_<employee_id>_<field>`, and the view re-derives the employee list fresh
at POST time and reads each employee's inputs back by that same key -- the
same "never trust a stale client-side list, always re-scope to what's true
right now" discipline CDV already applies to its AP-bill picks
(re-scoped to branch+vendor at submit, not the client's payload).
"""
from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, DecimalField, IntegerField
from wtforms.validators import DataRequired, InputRequired, NumberRange

from app.utils import ph_now
from app.utils.concurrency import RowVersionFormMixin


class PayrollRunForm(RowVersionFormMixin, FlaskForm):
    """Run header only. The employee line grid is handled server-side in the
    view/template (see module docstring)."""

    run_type = SelectField('Run Type', validators=[DataRequired()], choices=[
        ('regular', 'Regular'), ('13th_month', '13th Month')], default='regular')

    pay_frequency = SelectField('Pay Frequency', validators=[DataRequired()], choices=[
        ('monthly', 'Monthly'), ('semi_monthly', 'Semi-Monthly'),
        ('weekly', 'Weekly'), ('daily', 'Daily')])

    # '0' = not applicable (every frequency except semi-monthly); '1'/'2' pick
    # the cutoff for a semi-monthly run. Kept a plain string SelectField (not
    # coerce=int) so an unselected/blank POST fails validation instead of
    # silently coercing to 0 -- the view parses the int itself after validation.
    semi_period = SelectField('Cutoff', validators=[DataRequired()], choices=[
        ('0', 'N/A (not semi-monthly)'), ('1', '1st Cutoff'), ('2', '2nd Cutoff')],
        default='0')

    period_start = DateField('Period Start', validators=[DataRequired()], format='%Y-%m-%d')
    period_end = DateField('Period End', validators=[DataRequired()], format='%Y-%m-%d')
    pay_date = DateField('Pay Date', validators=[DataRequired()], format='%Y-%m-%d')


class ThirteenthMonthRunForm(RowVersionFormMixin, FlaskForm):
    """Task 14: run header for a run_type='13th_month' worksheet -- deliberately
    NOT the same form as PayrollRunForm. A 13th-month run has no pay-period
    concept (see the approved mockup, scratch/mockups/payroll-13th-month.html):
    no pay_frequency/period_start/period_end/semi_period picker, just the
    calendar Year (drives service.compute_thirteenth_month's YTD-basic lookup
    and the run's period_year/period_month/period_start/period_end, all
    derived by the view) and Pay Date. run_type itself is never a field here --
    it is fixed '13th_month' at the view layer (mirrors the mockup's read-only
    "Run Type: 13th Month" value, not a <select>), unlike PayrollRunForm where
    run_type is a real user choice.
    """
    year = IntegerField('Year', validators=[
        DataRequired(message='Year is required.'), NumberRange(min=2000, max=2100)],
        default=lambda: ph_now().year)
    pay_date = DateField('Pay Date', validators=[DataRequired()], format='%Y-%m-%d')


class EmployeeLoanForm(FlaskForm):
    """Task 12: create/edit an EmployeeLoan. `employee_id`/`loan_type` are only
    ever POSTed on create -- the edit route ignores them (an existing loan is
    never rebound to a different employee or type; create a new loan instead).
    They stay DataRequired/choice-validated on the form class itself because
    the edit template still submits the CURRENT values for those two fields
    (as plain, non-editable hidden inputs -- see loan_form.html), so validation
    still needs a matching choice to accept the round-tripped value.

    `principal`/`monthly_amortization`/`balance`/`status` are the fields this
    editor actually writes. See payroll.views._claim_loan_edit's docstring for
    how a stale write against `balance` (the one field also mutated by
    service.apply_loan_balances/restore_loan_balances) is guarded without a
    formal RowVersioned column -- the concurrency decision Task 12 was asked
    to make explicitly for this new write surface.
    """
    employee_id = SelectField('Employee', coerce=int, validators=[
        DataRequired(message='Employee is required.')])
    loan_type = SelectField('Loan Type', validators=[DataRequired()], choices=[
        ('sss', 'SSS'), ('pagibig', 'Pag-IBIG')])
    status = SelectField('Status', validators=[DataRequired()], choices=[
        ('active', 'Active'), ('paid', 'Paid'), ('cancelled', 'Cancelled')],
        default='active')
    # InputRequired, NOT DataRequired: DataRequired treats a falsy field.data
    # (Decimal('0.00') is falsy) as "missing", which would wrongly reject a
    # legitimate 0.00 balance (a fully paid-off loan) or 0.00 principal edge
    # case. InputRequired checks that raw form input was submitted at all,
    # independent of whether the parsed value happens to be zero.
    principal = DecimalField('Principal', validators=[
        InputRequired(message='Principal is required.'), NumberRange(min=0)], places=2)
    monthly_amortization = DecimalField('Monthly Amortization', validators=[
        InputRequired(message='Monthly amortization is required.'), NumberRange(min=0)], places=2)
    balance = DecimalField('Current Balance', validators=[
        InputRequired(message='Current balance is required.'), NumberRange(min=0)], places=2)
