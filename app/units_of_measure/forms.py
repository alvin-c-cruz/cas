"""Forms for Units of Measure master data."""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField
from wtforms.validators import DataRequired, Length


class UnitOfMeasureForm(FlaskForm):
    code = StringField('Code', validators=[
        DataRequired(message='Code is required.'),
        Length(max=20, message='Code must be 20 characters or less.')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=100, message='Name must be 100 characters or less.')])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
