"""
Forms for Purchase Bill management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class PurchaseBillForm(FlaskForm):
    """Form for creating and editing purchase bills."""

    bill_number = StringField('AP Number', validators=[
        DataRequired(message='Bill number is required.'),
        Length(max=50, message='Bill number must be 50 characters or less.')
    ])

    bill_date = DateField('Voucher Date', validators=[
        DataRequired(message='Bill date is required.')
    ], format='%Y-%m-%d', default=date.today)

    due_date = DateField('Due Date', validators=[
        DataRequired(message='Due date is required.')
    ], format='%Y-%m-%d')

    vendor_id = SelectField('Vendor', validators=[
        DataRequired(message='Vendor is required.')
    ], coerce=int)

    vendor_invoice_number = StringField('Vendor Invoice #', validators=[
        Optional(),
        Length(max=100, message='Vendor invoice number must be 100 characters or less.')
    ])

    vendor_invoice_date = DateField('Vendor Invoice Date', validators=[
        Optional()
    ], format='%Y-%m-%d')

    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment')
    ], default='Net 30')

    reference = StringField('Reference/PO Number', validators=[
        Optional(),
        Length(max=100, message='Reference must be 100 characters or less.')
    ])

    notes = TextAreaField('Notes', validators=[Optional()])
