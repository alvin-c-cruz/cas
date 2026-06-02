"""
Forms for Receipt/Payment management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, DecimalField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from datetime import date


class ReceiptForm(FlaskForm):
    """Form for creating and editing receipts/payments."""

    receipt_number = StringField('Receipt/Payment Number', validators=[
        DataRequired(message='Receipt number is required.'),
        Length(max=50, message='Receipt number must be 50 characters or less.')
    ])

    receipt_date = DateField('Date', validators=[
        DataRequired(message='Date is required.')
    ], format='%Y-%m-%d', default=date.today)

    transaction_type = SelectField('Transaction Type', validators=[
        DataRequired(message='Transaction type is required.')
    ], choices=[
        ('collection', 'Collection (from Customer)'),
        ('payment', 'Payment (to Vendor)')
    ])

    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    vendor_id = SelectField('Vendor', coerce=int, validators=[Optional()])

    payment_method = SelectField('Payment Method', validators=[
        DataRequired(message='Payment method is required.')
    ], choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online Payment')
    ])

    # Check details
    check_number = StringField('Check Number', validators=[
        Optional(),
        Length(max=50, message='Check number must be 50 characters or less.')
    ])

    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')

    check_bank = StringField('Bank Name', validators=[
        Optional(),
        Length(max=100, message='Bank name must be 100 characters or less.')
    ])

    # Bank/Cash account
    bank_account = StringField('Bank/Cash Account', validators=[
        Optional(),
        Length(max=100, message='Account must be 100 characters or less.')
    ])

    account_id = SelectField('Cash/Bank Account (GL)', coerce=int, validators=[Optional()])

    amount = DecimalField('Amount', validators=[
        DataRequired(message='Amount is required.'),
        NumberRange(min=0.01, message='Amount must be greater than zero.')
    ], places=2)

    reference = StringField('Reference/OR Number', validators=[
        Optional(),
        Length(max=100, message='Reference must be 100 characters or less.')
    ])

    notes = TextAreaField('Notes', validators=[Optional()])
