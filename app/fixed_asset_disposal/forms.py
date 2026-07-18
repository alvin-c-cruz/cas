from flask_wtf import FlaskForm
from wtforms import SelectField, DecimalField, DateField, TextAreaField
from wtforms.validators import DataRequired, Optional, NumberRange


class DisposalForm(FlaskForm):
    disposal_date = DateField('Disposal Date', validators=[
        DataRequired(message='Disposal date is required.')])
    disposal_type = SelectField('Disposal Type', choices=[
        ('sale', 'Sale'), ('scrap', 'Scrap / Write-off'), ('trade_in', 'Trade-in'),
    ], validators=[DataRequired()])
    proceeds_amount = DecimalField('Proceeds Amount', validators=[
        Optional(), NumberRange(min=0, message='Must be zero or more.')], default=0)
    proceeds_account_id = SelectField('Proceeds Account', validators=[Optional()],
                                      validate_choice=False)
    notes = TextAreaField('Notes', validators=[Optional()])


class VoidDisposalForm(FlaskForm):
    void_date = DateField('Void Date', validators=[
        DataRequired(message='Void date is required.')])
