from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DecimalField, DateField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional, Length


class PettyCashFundForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=20)])
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    account_id = SelectField('GL Petty Cash Account', coerce=int, validators=[DataRequired()])
    custodian = StringField('Custodian', validators=[Optional(), Length(max=200)])
    float_amount = DecimalField('Float Amount', places=2, validators=[DataRequired()])
    funding_bank_account_id = SelectField('Funding Bank Account', coerce=int, validators=[DataRequired()])


class PettyCashFundAdjustForm(FlaskForm):
    """Edit-mode: custodian/name changes don't post; a nonzero float_delta posts
    an adjustment JE via posting.post_adjust_float."""
    name = StringField('Name', validators=[DataRequired(), Length(max=200)])
    custodian = StringField('Custodian', validators=[Optional(), Length(max=200)])
    float_delta = DecimalField('Float Adjustment (+/-)', places=2, validators=[Optional()])


class PettyCashVoucherForm(FlaskForm):
    payee = StringField('Payee', validators=[DataRequired(), Length(max=200)])
    expense_account_id = SelectField('Expense Account', coerce=int, validators=[DataRequired()])
    amount = DecimalField('Amount', places=2, validators=[DataRequired()])
    description = StringField('Description', validators=[Optional(), Length(max=500)])
    receipt_ref = StringField('Receipt / OR Reference', validators=[Optional(), Length(max=100)])


class PettyCashReplenishForm(FlaskForm):
    physical_cash_counted = DecimalField('Physical Cash Counted', places=2, validators=[DataRequired()])
    # Comma-separated PettyCashVoucher ids, populated by the held-vouchers
    # checkbox table's JS (mirrors the checkbox-select pattern used by
    # accounts_payable/templates/accounts_payable/list.html's pb-row-check).
    selected_voucher_ids = HiddenField('Selected Vouchers', validators=[Optional()])
