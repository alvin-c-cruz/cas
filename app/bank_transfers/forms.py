from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField, TextAreaField
from wtforms.validators import DataRequired, Optional
from app.utils.concurrency import RowVersionFormMixin


class BankTransferForm(RowVersionFormMixin, FlaskForm):
    from_bank_account_id = SelectField('From Account', coerce=int, validators=[DataRequired()])
    to_bank_account_id = SelectField('To Account', coerce=int, validators=[DataRequired()])
    amount = DecimalField('Amount', places=2, validators=[DataRequired()])
    transfer_date = DateField('Transfer Date', validators=[DataRequired()])
    memo = TextAreaField('Memo', validators=[Optional()])
