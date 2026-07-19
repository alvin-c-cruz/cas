"""Forms for Work Center master data (R-07 D1)."""
from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SelectField
from wtforms.validators import DataRequired, Length, Optional


class WorkCenterForm(FlaskForm):
    code = StringField('Code', validators=[
        DataRequired(message='Code is required.'),
        Length(max=20, message='Code must be 20 characters or less.')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=200, message='Name must be 200 characters or less.')])
    hourly_rate = DecimalField('Hourly Rate', places=2, validators=[Optional()])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
