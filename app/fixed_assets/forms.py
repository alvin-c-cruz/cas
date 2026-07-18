from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from app.fixed_assets.models import DEPRECIATION_METHODS

_METHOD_CHOICES = [('', '-- None --')] + [(m, m.replace('_', ' ').title())
                                           for m in DEPRECIATION_METHODS]


class AssetCategoryForm(FlaskForm):
    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(max=100, message='Name must be 100 characters or less.')])
    default_useful_life_months = IntegerField('Default Useful Life (months)', validators=[
        Optional(), NumberRange(min=1, message='Must be at least 1 month.')])
    default_depreciation_method = SelectField('Default Depreciation Method',
                                               choices=_METHOD_CHOICES,
                                               validators=[Optional()])
    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
