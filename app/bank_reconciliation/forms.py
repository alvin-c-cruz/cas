from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, SelectField, StringField, HiddenField
from wtforms.validators import DataRequired, Optional, Length


class NewReconciliationForm(FlaskForm):
    statement_date = DateField('Statement Date', validators=[DataRequired()])
    statement_ending_balance = DecimalField('Statement Ending Balance', places=2, validators=[DataRequired()])


class CompleteReconciliationForm(FlaskForm):
    """Posted by the work page's Complete action -- ticked_line_ids is a
    comma-separated hidden field populated by JS (same pattern as
    petty_cash's replenish form's selected_voucher_ids)."""
    ticked_line_ids = HiddenField('Ticked Lines', validators=[Optional()])


class AdjustmentForm(FlaskForm):
    account_id = SelectField('Account', coerce=int, validators=[DataRequired()])
    amount = DecimalField('Amount', places=2, validators=[DataRequired()])
    direction = SelectField('Direction (as seen from the bank)', validators=[DataRequired()],
                            choices=[('credit', 'Credit (money left the account)'),
                                     ('debit', 'Debit (money came into the account)')])
    description = StringField('Description', validators=[DataRequired(), Length(max=500)])
