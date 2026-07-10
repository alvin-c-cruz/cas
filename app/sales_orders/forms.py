"""
Forms for Sales Order management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, HiddenField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin
from datetime import date


class SalesOrderForm(RowVersionFormMixin, FlaskForm):
    """Form for creating and editing sales orders. Operational only — no GL/WHT/payment fields."""

    so_number = StringField('SO #', validators=[
        DataRequired(message='SO number is required.'),
        Length(max=50)
    ])

    order_date = DateField('Order Date', validators=[
        DataRequired(message='Order date is required.')
    ], format='%Y-%m-%d', default=date.today)

    expected_delivery_date = DateField('Expected Delivery Date', validators=[Optional()],
                                       format='%Y-%m-%d')

    # Customer fields — customer_id is a hidden field managed by the JS customer picker;
    # customer_name/tin/address are populated client-side from the picker.
    customer_id = HiddenField('Customer ID', validators=[
        DataRequired(message='Customer is required.')
    ])

    customer_name = HiddenField('Customer Name')
    customer_tin = HiddenField('Customer TIN')
    customer_address = HiddenField('Customer Address')

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

    notes = TextAreaField('Notes', validators=[Optional()])

    # Hidden JSON blob carrying the line items submitted from the JS line-item grid.
    line_items_json = HiddenField('Line Items JSON')
