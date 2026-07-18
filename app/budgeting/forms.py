from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired, NumberRange


class BudgetGridForm(FlaskForm):
    """CSRF + fiscal-year carry-through only. Cell amounts are parsed from the raw
    request's amount_<account_id>_<month> fields (Task 4) -- the account set is
    dynamic per company's COA, so it can't be a fixed WTForms field list."""
    fiscal_year = IntegerField('Fiscal Year', validators=[
        DataRequired(), NumberRange(min=2000, max=2100)])
