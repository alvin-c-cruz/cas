from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, DateField, SelectField
from wtforms.validators import DataRequired, Optional, Length


class BankAccountForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=20)])
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    account_id = SelectField('GL Cash/Bank Account', coerce=int, validators=[DataRequired()])
    bank_name = StringField('Bank Name', validators=[Optional(), Length(max=200)])
    account_number = StringField('Account Number', validators=[Optional(), Length(max=50)])
    account_type = SelectField('Type', choices=[
        ('checking', 'Checking'), ('savings', 'Savings'), ('cash-on-hand', 'Cash on Hand')],
        validators=[Optional()])
    opening_balance = DecimalField('Opening Balance', places=2, default=0, validators=[Optional()])
    opening_date = DateField('Opening Date', validators=[Optional()])
    # Edit-only (Active/Inactive toggle, mockup-approved) — a new record is always
    # Active by default and this field is never rendered on the create form.
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')],
                            validators=[Optional()])
