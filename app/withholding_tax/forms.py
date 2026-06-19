"""
Withholding Tax forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class WithholdingTaxForm(FlaskForm):
    """Form for creating/editing withholding tax codes.

    A reason for the change is required when editing an existing record, but
    not when creating one (nothing is being changed — the reviewer judges the
    proposed data). Pass ``require_reason=True`` from the edit view.
    """
    code = StringField('ATC', validators=[
        DataRequired(message='ATC is required'),
        Length(max=20, message='ATC must be 20 characters or less')
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
    request_reason = TextAreaField('Reason for Change', validators=[
        Optional(),
        Length(max=500, message='Reason must be 500 characters or less')
    ], render_kw={'placeholder': 'Why is this change needed?', 'rows': 3})

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        if require_reason:
            self.request_reason.validators = [
                DataRequired(message='Please explain why this change is needed'),
                Length(max=500, message='Reason must be 500 characters or less')
            ]


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
