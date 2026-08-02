"""Forms for Manufacturing Department master data (R-07 P1).

Mirrors WorkCenterForm minus hourly_rate -- process mode allocates conversion cost
via ExpenseAllocationRule, not an hourly rate.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField
from wtforms.validators import DataRequired, Length


class ManufacturingDepartmentForm(FlaskForm):
    code = StringField('Code', validators=[
        DataRequired(message='Code is required.'),
        Length(max=20, message='Code must be 20 characters or less.')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=200, message='Name must be 200 characters or less.')])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
