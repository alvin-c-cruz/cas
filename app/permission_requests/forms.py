"""Permission Change Request forms."""
from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField, SelectMultipleField
from wtforms.validators import DataRequired, Length, Optional
from wtforms.widgets import ListWidget, CheckboxInput


class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()


class PermissionRequestForm(FlaskForm):
    """CA submits: target accountant + desired new book_permissions keys + reason."""
    target_user_id = SelectField('Target Accountant', coerce=int, validators=[DataRequired()])
    requested_keys = MultiCheckboxField(
        'Requested Permissions',
        validators=[DataRequired(message='Select at least one permission to request.')]
    )
    request_reason = TextAreaField('Reason', validators=[
        DataRequired(message='A reason is required.'),
        Length(max=500, message='Reason must be 500 characters or less')
    ])


class PermissionRequestReviewForm(FlaskForm):
    """Admin reviews: approve or reject, with optional notes."""
    action = SelectField('Action', choices=[
        ('approve', 'Approve'),
        ('reject', 'Reject')
    ], validators=[DataRequired()])
    review_notes = TextAreaField('Review Notes', validators=[
        Optional(),
        Length(max=500, message='Notes must be 500 characters or less')
    ])
