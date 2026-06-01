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

    default_vat = SelectField('Default VAT', choices=[
        ('', '-- Select VAT Type --'),
        ('VATOG 12%', 'VATOG 12% (VAT on Goods)'),
        ('VATSV 12%', 'VATSV 12% (VAT on Services)'),
        ('VAT-Exempt', 'VAT-Exempt'),
        ('Zero-Rated', 'Zero-Rated')
    ])

    default_wt = SelectField('Default Withholding Tax', choices=[
        ('', '-- Select WT Type --'),
        ('WC158', 'WC158 (2% - Goods)'),
        ('WC160', 'WC160 (1% - Services)'),
        ('WC100', 'WC100 (5% - Professional Fees)'),
        ('None', 'No Withholding Tax')
    ])

    address = TextAreaField('Address', validators=[Optional()])

    email = StringField('Email', validators=[
        Optional(),
        Email(message='Invalid email address.'),
        Length(max=120, message='Email must be 120 characters or less.')
    ])

    is_active = BooleanField('Active')
