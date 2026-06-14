"""
Forms for Company Settings
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Email, Optional


MONTH_CHOICES = [
    ('01', 'January'),
    ('02', 'February'),
    ('03', 'March'),
    ('04', 'April'),
    ('05', 'May'),
    ('06', 'June'),
    ('07', 'July'),
    ('08', 'August'),
    ('09', 'September'),
    ('10', 'October'),
    ('11', 'November'),
    ('12', 'December'),
]

VAT_REGISTRATION_CHOICES = [
    ('VAT', 'VAT'),
    ('Non-VAT', 'Non-VAT'),
]

APV_PRINT_ACCESS_CHOICES = [
    ('posted_only', 'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]


class CompanySettingsForm(FlaskForm):
    """Form for editing company-wide settings (stored as app_settings rows)."""

    # Company Identity
    company_name = StringField('Registered Company Name', validators=[
        DataRequired(message='Company name is required.'),
        Length(max=200, message='Company name must be 200 characters or less.')
    ])
    trade_name = StringField('Trade Name', validators=[
        Optional(),
        Length(max=200, message='Trade name must be 200 characters or less.')
    ])

    # BIR Registration
    company_tin = StringField('TIN', validators=[
        Optional(),
        Length(max=20, message='TIN must be 20 characters or less.')
    ])
    tin_branch_code = StringField('TIN Branch Code', validators=[
        Optional(),
        Length(max=10, message='TIN branch code must be 10 characters or less.')
    ])
    rdo_code = StringField('RDO Code', validators=[
        Optional(),
        Length(max=10, message='RDO code must be 10 characters or less.')
    ])
    vat_registration_type = SelectField(
        'VAT Registration Type', choices=VAT_REGISTRATION_CHOICES
    )

    # Address & Contact
    company_address = TextAreaField('Registered Address', validators=[
        Optional(),
        Length(max=200, message='Address must be 200 characters or less.')
    ])
    postal_code = StringField('Postal Code', validators=[
        Optional(),
        Length(max=10, message='Postal code must be 10 characters or less.')
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

    # Accounting
    fiscal_year_start = SelectField(
        'Fiscal Year Start Month', choices=MONTH_CHOICES
    )

    # Company Officers
    officer_president = StringField('President', validators=[
        Optional(),
        Length(max=200, message='Name must be 200 characters or less.')
    ])
    officer_treasurer = StringField('Treasurer', validators=[
        Optional(),
        Length(max=200, message='Name must be 200 characters or less.')
    ])
    officer_secretary = StringField('Corporate Secretary', validators=[
        Optional(),
        Length(max=200, message='Name must be 200 characters or less.')
    ])

    # Documents
    apv_print_access = SelectField(
        'APV Print Access', choices=APV_PRINT_ACCESS_CHOICES
    )
