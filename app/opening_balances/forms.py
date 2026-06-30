from flask_wtf import FlaskForm
from wtforms import DateField
from wtforms.validators import DataRequired
from datetime import date


class OpeningBalanceForm(FlaskForm):
    """CSRF + cutover date. Line rows are parsed from the raw request arrays."""
    cutover_date = DateField('Cutover Date', format='%Y-%m-%d',
                             default=date.today, validators=[DataRequired()])
