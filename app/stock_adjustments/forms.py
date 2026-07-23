from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, HiddenField
from wtforms.validators import DataRequired

from app.utils.concurrency import RowVersionFormMixin
from app.stock_adjustments.models import REASON_TYPES

# 'physical_count' is never manually selected -- it is set only by
# approve_physical_count() when it auto-generates a StockAdjustment. Showing
# it in this dropdown would let a user claim a manually-typed correction was
# count-driven, which it wasn't.
_MANUAL_REASON_CHOICES = [(r, r.replace('_', ' ').title())
                          for r in REASON_TYPES if r != 'physical_count']


class StockAdjustmentForm(RowVersionFormMixin, FlaskForm):
    """Stock Adjustment header form. Line items are carried as a JSON payload in
    the `lines` HiddenField (mirrors the sales-memo line editor)."""
    adjustment_date = DateField('Date', validators=[DataRequired()], format='%Y-%m-%d')
    reason_type = SelectField('Reason', choices=_MANUAL_REASON_CHOICES,
                              validators=[DataRequired()])
    notes = TextAreaField('Notes')
    lines = HiddenField('Lines JSON')


class PhysicalCountForm(RowVersionFormMixin, FlaskForm):
    """Physical Count header form. Branch is implicit (session-selected, same
    convention as StockAdjustmentForm) -- not a field here. The per-product
    counted-quantity grid is NOT part of this form: it is a fixed set of rows
    (one per PhysicalCountLine) parsed directly from request.form by the
    count-entry view, since WTForms has no clean way to bind a
    server-determined, non-reorderable set of named fields."""
    count_date = DateField('Count Date', validators=[DataRequired()], format='%Y-%m-%d')
    notes = TextAreaField('Notes')
