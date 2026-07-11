"""
Forms for Company Settings
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField
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

PRINT_ACCESS_CHOICES = [
    ('posted_only',      'Posted only'),
    ('draft_and_posted', 'Draft and posted'),
]

# Which print form a Sales Invoice uses (separate axis from print ACCESS, which
# gates by status). 'hidden' turns SI printing off entirely (button hidden AND
# the /print route refuses). Room for a 'preprinted' option when that module is
# rebuilt.
SV_PRINT_FORM_CHOICES = [
    ('current',    'Printable Form'),
    ('preprinted', 'Pre-printed Form'),
    ('hidden',     'Hidden (no print button)'),
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
        'APV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
    )
    sv_print_access = SelectField(
        'Sales Invoice Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
    )
    sv_print_form = SelectField(
        'Sales Invoice Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )
    so_print_form = SelectField(
        'Sales Order Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )
    cd_print_access = SelectField(
        'CDV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
    )
    cd_check_print_access = SelectField(
        'Check Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
    )
    cr_print_access = SelectField(
        'CRV Print Access', choices=PRINT_ACCESS_CHOICES, default='posted_only'
    )
    cr_print_form = SelectField(
        'Cash Receipt Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )
    ap_print_form = SelectField(
        'APV Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )
    cd_print_form = SelectField(
        'CDV Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )
    jv_print_form = SelectField(
        'JV Print Form', choices=SV_PRINT_FORM_CHOICES, default='current'
    )

    # Administration / policy
    accountant_email_self_approval = BooleanField(
        'Allow accountants to self-approve Staff/Viewer registration emails')

    si_dr_billing_consolidate = BooleanField(
        'Consolidate multiple Delivery Receipts into one Sales Invoice '
        '(off = one DR per invoice)')

    ap_billing_consolidate = BooleanField(
        'Consolidate multiple Purchase Orders / Receiving Reports into one Bill '
        '(off = one PO or RR per bill)')
