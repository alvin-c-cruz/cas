from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class CashDisbursementForm(FlaskForm):

    # Auto-generated server-side (CD-YYYY-MM-NNNN) and regenerated on POST — the
    # field is read-only so the client value is display-only and never trusted.
    cdv_number = StringField('CD Number', validators=[
        DataRequired(message='CDV number is required.'),
        Length(max=50, message='CDV number must be 50 characters or less.')
    ], render_kw={'readonly': True})

    cdv_date = DateField('CDV Date', validators=[
        DataRequired(message='CDV date is required.')
    ], format='%Y-%m-%d', default=date.today)

    vendor_id = SelectField('Vendor', validators=[
        DataRequired(message='Vendor is required.')
    ], coerce=int)

    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online'),
    ], default='cash')

    check_number = StringField('Check Number', validators=[
        Optional(),
        Length(max=50)
    ])

    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')

    check_bank = StringField('Bank', validators=[
        Optional(),
        Length(max=100)
    ])

    cash_account_id = SelectField('Cash / Bank Account', validators=[
        DataRequired(message='Cash or bank account is required.')
    ], coerce=int)

    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required — this becomes the Particulars in the CD Journal.')
    ])
