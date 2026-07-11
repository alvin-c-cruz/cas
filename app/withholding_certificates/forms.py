"""Form for the register of BIR 2307 certificates received from customers."""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, SelectField, DecimalField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class WithholdingCertificateReceivedForm(FlaskForm):
    branch_id = SelectField('Branch', coerce=int,
                            validators=[DataRequired(message='Branch is required.')])
    customer_id = SelectField('Customer (Payor)', coerce=int,
                              validators=[DataRequired(message='Customer is required.')])
    certificate_number = StringField('Certificate Number', validators=[
        DataRequired(message='Certificate number is required.'), Length(max=50)])
    date_received = DateField('Date Received', validators=[DataRequired()], format='%Y-%m-%d')
    period_from = DateField('Period From', validators=[DataRequired()], format='%Y-%m-%d')
    period_to = DateField('Period To', validators=[DataRequired()], format='%Y-%m-%d')
    wt_id = SelectField('ATC (Withholding Code)', coerce=int,
                        validators=[DataRequired(message='ATC is required.')])
    income_payment = DecimalField('Income Payment', places=2,
                                  validators=[DataRequired(), NumberRange(min=0)])
    tax_withheld = DecimalField('Tax Withheld', places=2,
                                validators=[DataRequired(), NumberRange(min=0)])
    notes = TextAreaField('Notes', validators=[Optional()])
