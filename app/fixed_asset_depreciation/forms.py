from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, DateField
from wtforms.validators import DataRequired, NumberRange


class DepreciationRunPeriodForm(FlaskForm):
    branch_id = SelectField('Branch', coerce=int, validators=[
        DataRequired(message='Branch is required.')], validate_choice=False)
    period_year = IntegerField('Year', validators=[
        DataRequired(message='Year is required.'),
        NumberRange(min=2000, max=2100, message='Enter a valid year.')])
    period_month = IntegerField('Month', validators=[
        DataRequired(message='Month is required.'),
        NumberRange(min=1, max=12, message='Month must be 1-12.')])


class ReversalForm(FlaskForm):
    reversal_date = DateField('Reversal Date', validators=[
        DataRequired(message='Reversal date is required.')])
