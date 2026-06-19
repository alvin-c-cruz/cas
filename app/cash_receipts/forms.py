from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from datetime import date


class CashReceiptForm(FlaskForm):
    crv_number = StringField('CR Number', validators=[
        DataRequired(message='CRV number is required.'),
        Length(max=50, message='CRV number must be 50 characters or less.')
    ], render_kw={'readonly': True})

    crv_date = DateField('CRV Date', validators=[
        DataRequired(message='CRV date is required.')
    ], format='%Y-%m-%d', default=date.today)

    customer_id = SelectField('Customer', validators=[
        DataRequired(message='Customer is required.')
    ], coerce=int)

    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online'),
    ], default='cash')

    check_number = StringField('Check Number', validators=[Optional(), Length(max=50)])
    check_date = DateField('Check Date', validators=[Optional()], format='%Y-%m-%d')
    check_bank = StringField('Bank', validators=[Optional(), Length(max=100)])

    cash_account_id = SelectField('Cash / Bank Account', validators=[
        DataRequired(message='Cash or bank account is required.')
    ], coerce=int)

    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required.')
    ])
