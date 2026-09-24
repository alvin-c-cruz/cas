from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from app.utils.concurrency import RowVersionFormMixin
from datetime import date


class CashDisbursementForm(RowVersionFormMixin, FlaskForm):

    # Pre-filled with the next auto-generated CD-YYYY-MM-NNNN sequence as a
    # suggested default, but editable by the user.  Uniqueness is validated
    # server-side in the create and edit views.
    cdv_number = StringField('CD Number', validators=[
        DataRequired(message='CDV number is required.'),
        Length(max=50, message='CDV number must be 50 characters or less.')
    ])

    cdv_date = DateField('CDV Date', validators=[
        DataRequired(message='CDV date is required.')
    ], format='%Y-%m-%d', default=date.today)

    # 'vendor:<id>' | 'employee:<id>' -- the APV's payee shape (2026-09-24).
    # Parsed and resolved in the view (app.common.payee); the picker fills it.
    payee = StringField('Payee', validators=[DataRequired(message='Payee is required.')])

    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online'),
    ], default='cash')

    check_number = StringField('Check Number', validators=[
        Optional(),
        Length(max=50)
    ])

    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')

    check_bank = StringField('Bank', validators=[
        Optional(),
        Length(max=100)
    ])

    cash_account_id = SelectField('Cash / Bank Account', validators=[
        DataRequired(message='Cash or bank account is required.')
    ], coerce=int)

    notes = TextAreaField('Notes (Particulars)', validators=[Optional()])

    def validate_notes(self, field):
        """Notes/particulars are required only when the disbursement includes direct
        expense lines (Section B). AP-payment-only disbursements (Section A) take
        their particulars from the referenced bills, so notes are optional."""
        import json
        from flask import request
        raw = request.form.get('expense_lines', '') or '[]'
        try:
            has_expense = bool(json.loads(raw))
        except (ValueError, TypeError):
            has_expense = False
        if has_expense and not (field.data or '').strip():
            raise ValidationError('Notes are required when the disbursement includes direct expense lines.')
