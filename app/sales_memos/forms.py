from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, StringField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional, Length
from datetime import date


DESTINATION_CHOICES = [
    ('ar', 'Apply to the invoice (reduce Accounts Receivable)'),
    ('cash_refund', 'Cash refund'),
    ('customer_credit', 'Customer credit balance'),
]


class SalesMemoForm(FlaskForm):
    """Shared Credit/Debit memo header form. The memo_type is fixed by the route."""
    sales_invoice_id = SelectField('Sales Invoice', coerce=int,
                                   validators=[DataRequired()], validate_choice=False)
    memo_date = DateField('Date', validators=[DataRequired()],
                          format='%Y-%m-%d', default=date.today)
    reason = TextAreaField('Reason', validators=[DataRequired(), Length(min=3, max=500)])
    reference = StringField('Reference', validators=[Optional(), Length(max=100)])
    destination = SelectField('Destination', choices=DESTINATION_CHOICES,
                              validators=[DataRequired()], default='ar')
    cash_account_id = SelectField('Cash Account', coerce=int,
                                  validators=[Optional()], validate_choice=False)
    salesperson_id = SelectField('Salesperson', coerce=int,
                                 validators=[Optional()], validate_choice=False)
    notes = TextAreaField('Notes', validators=[Optional()])
    lines = HiddenField('Lines JSON')
