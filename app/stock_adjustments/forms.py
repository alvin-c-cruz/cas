from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, HiddenField
from wtforms.validators import DataRequired

from app.utils.concurrency import RowVersionFormMixin
from app.stock_adjustments.models import REASON_TYPES


class StockAdjustmentForm(RowVersionFormMixin, FlaskForm):
    """Stock Adjustment header form. Line items are carried as a JSON payload in
    the `lines` HiddenField (mirrors the sales-memo line editor)."""
    adjustment_date = DateField('Date', validators=[DataRequired()], format='%Y-%m-%d')
    reason_type = SelectField('Reason', choices=[(r, r.title()) for r in REASON_TYPES],
                              validators=[DataRequired()])
    notes = TextAreaField('Notes')
    lines = HiddenField('Lines JSON')
