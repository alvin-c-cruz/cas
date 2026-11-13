"""Forms for Employee master."""
from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, DateField, SelectField,
                     IntegerField, DecimalField, BooleanField)
from wtforms.validators import DataRequired, Length, Optional, Email, NumberRange


class EmployeeForm(FlaskForm):
    employee_no = StringField('Employee No.', validators=[
        DataRequired(message='Employee number is required.'),
        Length(max=20)])
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=100)])
    middle_name = StringField('Middle Name', validators=[Optional(), Length(max=100)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=100)])
    birthdate = DateField('Birthdate', validators=[Optional()], format='%Y-%m-%d')
    address = TextAreaField('Address', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])

    tin = StringField('TIN', validators=[Optional(), Length(max=50)])
    sss_no = StringField('SSS No.', validators=[Optional(), Length(max=50)])
    philhealth_no = StringField('PhilHealth No.', validators=[Optional(), Length(max=50)])
    pagibig_no = StringField('Pag-IBIG No.', validators=[Optional(), Length(max=50)])

    date_hired = DateField('Date Hired', validators=[Optional()], format='%Y-%m-%d')
    employment_status = SelectField('Employment Status', validators=[Optional()], choices=[
        ('', '— select —'), ('regular', 'Regular'), ('probationary', 'Probationary'),
        ('contractual', 'Contractual'), ('part-time', 'Part-time')])
    position = StringField('Position (HR title)', validators=[Optional(), Length(max=120)])

    branch_id = SelectField('Branch', coerce=int, validators=[
        DataRequired(message='Branch is required.')])

    tax_status_code = StringField('Tax Status Code', validators=[Optional(), Length(max=10)])
    qualified_dependents = IntegerField('Qualified Dependents', validators=[
        Optional(), NumberRange(min=0)], default=0)
    is_minimum_wage = BooleanField('Minimum-Wage Earner')
    is_salesperson = BooleanField('Salesperson (can be credited on sales documents)')

    pay_basis = SelectField('Pay Basis', validators=[Optional()], choices=[
        ('', '— select —'), ('monthly', 'Monthly'), ('daily', 'Daily')])
    basic_rate = DecimalField('Basic Rate', validators=[Optional(), NumberRange(min=0)], places=2)
    pay_frequency = SelectField('Pay Frequency', validators=[Optional()], choices=[
        ('', '— select —'), ('monthly', 'Monthly'), ('semi-monthly', 'Semi-monthly'),
        ('weekly', 'Weekly')])

    # Optional identity link. Choices set in the view: [('', '— none —'), (user.id, label), ...]
    user_id = SelectField('Linked User (optional)', validators=[Optional()], coerce=lambda v: int(v) if v else None)

    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])

    # The account a payroll deposit goes into (owner, 10 Nov 2026: "EMP-B"), as on the vendor.
    bank_name = StringField('Bank', validators=[Optional(), Length(max=100)])
    bank_account_name = StringField('Account Name', validators=[Optional(), Length(max=200)])
    bank_account_number = StringField('Account Number', validators=[Optional(), Length(max=50)])
    # The cheque payee when not the employee's own name, e.g. CASH (plan 2.3).
    check_payee_name = StringField('Check Payee Name', validators=[Optional(), Length(max=200)])
    # The bank form this employee's deposit slip opens on; blank follows the bank name
    # ("VS-4 A"). Choices are filled from the slip forms in __init__.
    deposit_slip_form = SelectField('Deposit Slip Form', choices=[], default='')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.common.deposit_slip import FORMS
        self.deposit_slip_form.choices = [('', '— follow bank name')] + [
            (key, form['label']) for key, form in FORMS.items()]
        if self.deposit_slip_form.data is None:      # a NULL employee, or a post without the field
            self.deposit_slip_form.data = ''
