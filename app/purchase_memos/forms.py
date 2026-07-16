"""Vendor Debit Memo header form -- buy-side mirror of app/sales_memos/forms.py.

Only one memo_type ('debit') is wired in Task 4 (a future Vendor Credit Memo would
reuse the same model with memo_type='credit', out of scope here). No salesperson
field -- PurchaseMemo has no salesperson_id (unlike SalesMemo)."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, StringField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional, Length
from datetime import date


DESTINATION_CHOICES = [
    ('ap', 'Apply to the bill (reduce Accounts Payable)'),
    ('cash_refund', 'Cash refund'),
    ('vendor_credit', 'Vendor credit balance'),
]


class PurchaseMemoForm(FlaskForm):
    """Vendor Debit Memo header form. The memo_type is fixed by the route ('debit')."""
    accounts_payable_id = SelectField('Accounts Payable Bill', coerce=int,
                                      validators=[DataRequired()], validate_choice=False)
    memo_date = DateField('Date', validators=[DataRequired()],
                          format='%Y-%m-%d', default=date.today)
    reason = TextAreaField('Reason', validators=[DataRequired(), Length(min=3, max=500)])
    reference = StringField('Reference', validators=[Optional(), Length(max=100)])
    destination = SelectField('Destination', choices=DESTINATION_CHOICES,
                              validators=[DataRequired()], default='ap')
    cash_account_id = SelectField('Cash Account', coerce=int,
                                  validators=[Optional()], validate_choice=False)
    notes = TextAreaField('Notes', validators=[Optional()])
    lines = HiddenField('Lines JSON')
