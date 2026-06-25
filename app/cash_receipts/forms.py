from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from datetime import date


class CashReceiptForm(FlaskForm):
    # Pre-printed receipt serial typed in by the accountant (like SI invoice_number),
    # not a system-generated sequence — so it is editable, not readonly.
    crv_number = StringField('CR Number', validators=[
        DataRequired(message='CRV number is required.'),
        Length(max=50, message='CRV number must be 50 characters or less.')
    ])

    crv_date = DateField('CRV Date', validators=[
        DataRequired(message='CRV date is required.')
    ], format='%Y-%m-%d', default=date.today)

    customer_id = SelectField('Customer', validators=[
        DataRequired(message='Customer is required.')
    ], coerce=int)

    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online'),
    ], default='cash')

    check_number = StringField('Check Number', validators=[Optional(), Length(max=50)])
    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')
    check_bank = StringField('Bank', validators=[Optional(), Length(max=100)])

    cash_account_id = SelectField('Cash / Bank Account', validators=[
        DataRequired(message='Cash or bank account is required.')
    ], coerce=int)

    notes = TextAreaField('Notes (Particulars)', validators=[Optional()])

    def validate_notes(self, field):
        """Notes/particulars are required only when the receipt includes direct
        revenue lines (Section B). AR-collection-only receipts (Section A) take
        their particulars from the referenced invoices, so notes are optional."""
        import json
        from flask import request
        raw = request.form.get('revenue_lines', '') or '[]'
        try:
            has_revenue = bool(json.loads(raw))
        except (ValueError, TypeError):
            has_revenue = False
        if has_revenue and not (field.data or '').strip():
            raise ValidationError('Notes are required when the receipt includes direct revenue lines.')
