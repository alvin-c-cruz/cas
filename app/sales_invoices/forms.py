"""
Forms for Sales Invoice management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin
from datetime import date


class SalesInvoiceForm(RowVersionFormMixin, FlaskForm):
    """Form for creating and editing sales invoices."""

    invoice_number = StringField('Invoice #', validators=[
        DataRequired(message='Invoice number is required.'),
        Length(max=50)
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

    customer_po_number = StringField('Customer PO #', validators=[
        Optional(), Length(max=100)
    ])

    customer_po_date = DateField('Customer PO Date', validators=[Optional()],
                                 format='%Y-%m-%d')

    payment_terms = SelectField('Payment Terms', validators=[DataRequired()], choices=[
        ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'), ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment'),
    ], default='Net 30')

    reference = StringField('Reference', validators=[Optional(), Length(max=100)])

    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)

    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required — this becomes the Particulars in the Sales Journal.')
    ])
