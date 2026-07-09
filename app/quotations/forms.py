"""Forms for Quotation management. Operational only -- no GL/WHT/payment fields.
Mirrors SalesOrderForm plus a header vat_treatment and a validity date. The quotation
number is server-generated (QTN-YYYY-MM-####), so it is not a form field."""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, HiddenField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class QuotationForm(FlaskForm):
    quotation_date = DateField('Quotation Date', validators=[
        DataRequired(message='Quotation date is required.')
    ], format='%Y-%m-%d', default=date.today)

    valid_until = DateField('Valid Until', validators=[Optional()], format='%Y-%m-%d')

    # Customer fields -- customer_id is a hidden field managed by the JS customer picker;
    # customer_name/tin/address are populated client-side from the picker (snapshot on save).
    customer_id = HiddenField('Customer ID', validators=[
        DataRequired(message='Customer is required.')
    ])
    customer_name = HiddenField('Customer Name')
    customer_tin = HiddenField('Customer TIN')
    customer_address = HiddenField('Customer Address')

    vat_treatment = SelectField('VAT Treatment', choices=[
        ('inclusive', 'VAT-Inclusive'), ('exclusive', 'VAT-Exclusive'),
        ('zero_rated', 'Zero-Rated')], default='inclusive')

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
