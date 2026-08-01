"""
Forms for Customer management
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired, Length, Email, Optional


class CustomerForm(FlaskForm):
    """Form for creating and editing customers."""

    code = StringField('Customer Code', validators=[
        DataRequired(message='Customer code is required.'),
        Length(max=20, message='Customer code must be 20 characters or less.')
    ])

    name = StringField('Registered Name', validators=[
        DataRequired(message='Customer name is required.'),
        Length(max=200, message='Customer name must be 200 characters or less.')
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
        Length(max=50, message='TIN must be 50 characters or less.')
    ])

    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment')
    ])

    is_active = SelectField('Status', choices=[
        ('1', 'Active'),
        ('0', 'Inactive')
    ])

    address = TextAreaField('Address', validators=[Optional()])

    postal_code = StringField('Postal Code', validators=[
        Optional(),
        Length(max=20, message='Postal code must be 20 characters or less.')
    ])

    vendor_code = StringField("Customer's Code for Us", validators=[
        Optional(),
        Length(max=50, message='Vendor code must be 50 characters or less.')
    ])

    default_vat_category = SelectField('Registration Type', choices=[], validators=[Optional()])

    default_wt_code = SelectField('Withholding Tax', choices=[], validators=[Optional()])

    default_salesperson_id = SelectField('Default Salesperson', choices=[], validators=[Optional()])

    po_required = BooleanField('Requires Purchase Order')


class CustomerDeliverySiteForm(FlaskForm):
    """Form for creating/editing one of a Customer's delivery sites.

    Name only -- no Address field (owner decision, mirrors the CustomerDeliverySite
    model, which has no address column either).
    """

    name = StringField('Delivery Site Name', validators=[
        DataRequired(message='Delivery site name is required.'),
        Length(max=200, message='Delivery site name must be 200 characters or less.')
    ])
