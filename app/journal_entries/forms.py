"""
Forms for Journal Entry management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class JournalEntryForm(FlaskForm):
    """Form for creating and editing journal entries."""

    entry_number = StringField('Entry Number', validators=[
        DataRequired(message='Entry number is required.'),
        Length(max=50, message='Entry number must be 50 characters or less.')
    ])

    entry_date = DateField('Entry Date', validators=[
        DataRequired(message='Entry date is required.')
    ], format='%Y-%m-%d', default=date.today)

    description = StringField('Description', validators=[
        DataRequired(message='Description is required.'),
        Length(max=500, message='Description must be 500 characters or less.')
    ])

    reference = StringField('Reference', validators=[
        Optional(),
        Length(max=100, message='Reference must be 100 characters or less.')
    ])

    entry_type = SelectField('Entry Type', choices=[
        ('adjustment', 'Adjustment'),
        ('closing', 'Closing Entry'),
        ('opening', 'Opening Entry'),
        ('reversal', 'Reversal'),
        ('reclassification', 'Reclassification')
    ], default='adjustment')

    is_reversing = BooleanField('Auto-reverse on next period')

    reversal_date = DateField('Reversal Date', validators=[Optional()], format='%Y-%m-%d')
