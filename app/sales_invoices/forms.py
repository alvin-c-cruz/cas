"""
Forms for Sales Invoice management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, DecimalField, FieldList, FormField
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from datetime import date


class SalesInvoiceItemForm(FlaskForm):
    """Form for a single invoice line item."""

    line_number = DecimalField('Line #', validators=[Optional()])

    description = StringField('Description', validators=[
        DataRequired(message='Description is required.'),
        Length(max=500, message='Description must be 500 characters or less.')
    ])

    quantity = DecimalField('Quantity', validators=[
        DataRequired(message='Quantity is required.'),
        NumberRange(min=0.0001, message='Quantity must be greater than zero.')
    ], places=4, default=1.0000)

    unit_price = DecimalField('Unit Price', validators=[
        DataRequired(message='Unit price is required.'),
        NumberRange(min=0, message='Unit price cannot be negative.')
    ], places=2, default=0.00)

    vat_category = SelectField('VAT Category', choices=[], validators=[Optional()])

    account_id = SelectField('Revenue Account', choices=[], validators=[Optional()], coerce=int)


class SalesInvoiceForm(FlaskForm):
    """Form for creating and editing sales invoices."""

    invoice_number = StringField('Invoice Number', validators=[
        DataRequired(message='Invoice number is required.'),
        Length(max=50, message='Invoice number must be 50 characters or less.')
    ])

    invoice_date = DateField('Invoice Date', validators=[
        DataRequired(message='Invoice date is required.')
    ], format='%Y-%m-%d', default=date.today)

    due_date = DateField('Due Date', validators=[
        DataRequired(message='Due date is required.')
    ], format='%Y-%m-%d')

    customer_id = SelectField('Customer', validators=[
        DataRequired(message='Customer is required.')
    ], coerce=int)

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

    # Line items would be handled via JavaScript in the template
    # and submitted as separate form data
