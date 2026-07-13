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
from wtforms import SelectField, DateField
from wtforms.validators import DataRequired

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
