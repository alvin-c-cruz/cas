"""Vendor Debit Memo / Vendor Credit Memo header form -- buy-side mirror of
app/sales_memos/forms.py. Shared by both memo types; the route fixes memo_type
and the view sets form.destination.choices = DESTINATION_CHOICES[memo_type] per
request (mirrors how accounts_payable_id.choices is already set dynamically).
No salesperson field -- PurchaseMemo has no salesperson_id (unlike SalesMemo)."""
from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, StringField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional, Length
from datetime import date


DESTINATION_CHOICES = {
    'debit': [
        ('ap', 'Apply to the bill (reduce Accounts Payable)'),
        ('cash_refund', 'Cash refund'),
        ('vendor_credit', 'Vendor credit balance'),
    ],
    'credit': [
        ('ap', 'Apply to the bill (increase Accounts Payable)'),
        ('cash_refund', 'Paid in cash'),
        ('vendor_credit', 'Apply against vendor credit balance'),
    ],
}


class PurchaseMemoForm(FlaskForm):
    """Shared Vendor Debit Memo / Vendor Credit Memo header form. The memo_type is
    fixed by the route; destination choices/labels are set per-type by the view."""
    accounts_payable_id = SelectField('Accounts Payable Bill', coerce=int,
                                      validators=[DataRequired()], validate_choice=False)
    memo_date = DateField('Date', validators=[DataRequired()],
                          format='%Y-%m-%d', default=date.today)
    reason = TextAreaField('Reason', validators=[DataRequired(), Length(min=3, max=500)])
    reference = StringField('Reference', validators=[Optional(), Length(max=100)])
    destination = SelectField('Destination', choices=[],
                              validators=[DataRequired()], default='ap')
    cash_account_id = SelectField('Cash Account', coerce=int,
                                  validators=[Optional()], validate_choice=False)
    notes = TextAreaField('Notes', validators=[Optional()])
    lines = HiddenField('Lines JSON')
