"""Sales VAT Category forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import (DataRequired, InputRequired, Length, NumberRange,
                                Optional, ValidationError)

from app.sales_vat_categories.models import SALES_NATURES, SALES_NATURE_LABELS

TRANSACTION_NATURE_CHOICES = [(n, SALES_NATURE_LABELS[n]) for n in SALES_NATURES]


class SalesVATCategoryForm(FlaskForm):
    """Form for creating/editing Sales VAT categories."""
    code = StringField('Sales VAT Code', validators=[
        DataRequired(message='Sales VAT code is required'),
        Length(max=20, message='Code must be 20 characters or less')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required'),
        Length(max=100, message='Name must be 100 characters or less')])
    description = TextAreaField('Description', validators=[
        Optional(), Length(max=500, message='Description must be 500 characters or less')])
    rate = DecimalField('VAT Rate (%)', validators=[
        InputRequired(message='VAT rate is required'),
        NumberRange(min=0, max=100, message='VAT rate must be between 0 and 100')], places=2)

    transaction_nature = SelectField('Transaction Nature',
                                     choices=TRANSACTION_NATURE_CHOICES,
                                     validators=[DataRequired()], default='regular')
    output_vat_account_id = SelectField('Output Tax Account', coerce=int,
                                        validators=[], default=0)

    def validate_output_vat_account_id(self, field):
        rate = self.rate.data
        if rate is not None and rate > 0:
            if not field.data or field.data == 0:
                raise ValidationError(
                    'Output Tax account is required for VAT-bearing categories.')
        else:
            field.data = 0

    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')],
                            validators=[DataRequired()])
    request_reason = TextAreaField('Reason for Change', validators=[
        Optional(), Length(max=500, message='Reason must be 500 characters or less')],
        render_kw={'placeholder': 'Why is this change needed?', 'rows': 3})

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        if require_reason:
            self.request_reason.validators = [
                DataRequired(message='Please explain why this change is needed'),
                Length(max=500, message='Reason must be 500 characters or less')]


class SalesVATCategoryChangeReviewForm(FlaskForm):
    """Form for reviewing change requests."""
    action = SelectField('Action', choices=[('approve', 'Approve'), ('reject', 'Reject')],
                         validators=[DataRequired()])
    review_notes = TextAreaField('Review Notes', validators=[
        Optional(), Length(max=500, message='Notes must be 500 characters or less')])
