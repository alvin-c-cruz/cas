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

    name = StringField('Vendor Name', validators=[
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

    tin = StringField('Tax Identification Number (TIN)', validators=[
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

    address = TextAreaField('Address', validators=[Optional()])

    email = StringField('Email', validators=[
        Optional(),
        Email(message='Invalid email address.'),
        Length(max=120, message='Email must be 120 characters or less.')
    ])

    check_payee_name = StringField('Check Payee Name', validators=[
        Optional(),
        Length(max=200, message='Check payee name must be 200 characters or less.')
    ])

    postal_code = StringField('Postal Code', validators=[
        Optional(),
        Length(max=20, message='Postal code must be 20 characters or less.')
    ])

    default_vat_category = SelectField('Default VAT Category', choices=[
        ('', '-- Select VAT Category --'),
        ('Other Goods (12%)', 'Other Goods (12%)'),
        ('Services (12%)', 'Services (12%)'),
        ('Capital Goods (12%)', 'Capital Goods (12%)'),
        ('VAT-Exempt', 'VAT-Exempt'),
        ('Zero-Rated', 'Zero-Rated')
    ])

    # Withholding Tax checkboxes
    wt_wc010 = BooleanField('WC010 Prof. Fees - Individuals (10%)')
    wt_wc011 = BooleanField('WC011 Prof. Fees - Corporations (15%)')
    wt_wc100 = BooleanField('WC100 Contractors & Subcontractors (2%)')
    wt_wc158 = BooleanField('WC158 Purchases of Goods (1%)')

    is_active = BooleanField('Active')
