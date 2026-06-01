"""
Withholding Tax forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class WithholdingTaxForm(FlaskForm):
    """Form for creating/editing withholding tax codes"""
    code = StringField('WT Code', validators=[
        DataRequired(message='WT code is required'),
        Length(max=20, message='WT code must be 20 characters or less')
    ])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required'),
        Length(max=100, message='Name must be 100 characters or less')
    ])
    description = TextAreaField('Description', validators=[
        Optional(),
        Length(max=500, message='Description must be 500 characters or less')
    ])
    rate = DecimalField('WT Rate (%)', validators=[
        DataRequired(message='WT rate is required'),
        NumberRange(min=0, max=100, message='WT rate must be between 0 and 100')
    ], places=2)
    is_active = SelectField('Status', choices=[
        ('1', 'Active'),
        ('0', 'Inactive')
    ], validators=[DataRequired()])


class WithholdingTaxChangeReviewForm(FlaskForm):
    """Form for reviewing change requests"""
    action = SelectField('Action', choices=[
        ('approve', 'Approve'),
        ('reject', 'Reject')
    ], validators=[DataRequired()])
    review_notes = TextAreaField('Review Notes', validators=[
        Optional(),
        Length(max=500, message='Notes must be 500 characters or less')
    ])
