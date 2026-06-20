"""Sales VAT Category forms."""
from decimal import Decimal
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import (DataRequired, InputRequired, Length, NumberRange,
                                Optional, ValidationError)

TRANSACTION_NATURE_CHOICES = [
    ('regular', 'Regular VATable'),
    ('zero_export', 'Zero-Rated (Export)'),
    ('zero_other', 'Zero-Rated (Other)'),
    ('exempt', 'VAT-Exempt'),
    ('government', 'Sales to Government'),
]


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
        DataRequired(message='VAT rate is required')], places=2)

    def validate_rate(self, field):
        """Validate rate is between 0 and 100."""
        # Coerce string data to Decimal if needed (happens with form.process(data=...))
        if isinstance(field.data, str):
            try:
                field.data = Decimal(field.data)
            except (ValueError, TypeError):
                raise ValidationError('VAT rate must be a valid number')
        if field.data is not None and (field.data < 0 or field.data > 100):
            raise ValidationError('VAT rate must be between 0 and 100')

    transaction_nature = SelectField('Transaction Nature',
                                     choices=TRANSACTION_NATURE_CHOICES,
                                     validators=[DataRequired()], default='regular')
    output_vat_account_id = SelectField('Output Tax Account', coerce=int,
                                        validators=[], default=0)

    def validate_output_vat_account_id(self, field):
        rate = self.rate.data
        # Handle case where rate might be a string (from form.process(data=...))
        if isinstance(rate, str):
            try:
                from decimal import Decimal
                rate = Decimal(rate)
            except (ValueError, TypeError):
                rate = None
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
