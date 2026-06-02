"""
Forms for Vendor management
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SelectField
from wtforms.validators import DataRequired, Length, Email, Optional


class VendorForm(FlaskForm):
    """Form for creating and editing vendors."""

    code = StringField('Vendor Code', validators=[
        DataRequired(message='Vendor code is required.'),
        Length(max=20, message='Vendor code must be 20 characters or less.')
    ])

    name = StringField('Name', validators=[
        DataRequired(message='Vendor name is required.'),
        Length(max=200, message='Vendor name must be 200 characters or less.')
    ])

    contact_person = StringField('Contact Person', validators=[
        Optional(),
        Length(max=200, message='Contact person must be 200 characters or less.')
    ])

    phone = StringField('Phone', validators=[
        Optional(),
        Length(max=50, message='Phone must be 50 characters or less.')
    ])

    email = StringField('Email', validators=[
        Optional(),
        Email(message='Invalid email address.'),
        Length(max=120, message='Email must be 120 characters or less.')
    ])

    tin = StringField('TIN', validators=[
        Optional(),
        Length(max=20, message='TIN must be 20 characters or less.')
    ])

    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('COD', 'Cash on Delivery'),
        ('Advance', 'Advance Payment')
    ])

    is_active = SelectField('Status', choices=[
        ('1', 'Active'),
        ('0', 'Inactive')
    ])

    address = TextAreaField('Address', validators=[Optional()])

    check_payee_name = StringField('Check Payee Name', validators=[
        Optional(),
        Length(max=200, message='Check payee name must be 200 characters or less.')
    ])

    postal_code = StringField('Postal Code', validators=[
        Optional(),
        Length(max=20, message='Postal code must be 20 characters or less.')
    ])

    default_vat_category = SelectField('Default VAT Category', choices=[], validators=[Optional()])
