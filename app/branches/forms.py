"""
Forms for Branch management
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SelectMultipleField
from wtforms.fields import ColorField
from wtforms.validators import DataRequired, Length, Email, Optional, Regexp


class BranchForm(FlaskForm):
    """Form for creating and editing branches."""
    code = StringField('Branch Code', validators=[
        DataRequired(message='Branch code is required.'),
        Length(max=20, message='Branch code must be 20 characters or less.')
    ])
    name = StringField('Branch Name', validators=[
        DataRequired(message='Branch name is required.'),
        Length(max=200, message='Branch name must be 200 characters or less.')
    ])
    address = TextAreaField('Address', validators=[Optional()])
    phone = StringField('Phone', validators=[
        Optional(),
        Length(max=50, message='Phone must be 50 characters or less.')
    ])
    email = StringField('Email', validators=[
        Optional(),
        Email(message='Invalid email address.'),
        Length(max=120, message='Email must be 120 characters or less.')
    ])
    is_active = BooleanField('Active')
    use_custom_theme = BooleanField('Use a custom sidebar color for this branch')
    theme_color = ColorField('Sidebar Color', validators=[
        Optional(),
        Regexp(r'^#[0-9a-fA-F]{6}$', message='Must be a valid #RRGGBB color.')
    ])
