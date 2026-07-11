"""Forms for Receiving Report management. Buy-side mirror of DeliveryReceiptForm."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Optional
from app.utils.concurrency import RowVersionFormMixin


class ReceivingReportForm(RowVersionFormMixin, FlaskForm):
    purchase_order_id = SelectField('Purchase Order', coerce=int, validate_choice=False,
                                    validators=[DataRequired(message='Select a Purchase Order.')])
    receipt_date = DateField('Receipt Date', validators=[
        DataRequired(message='Receipt date is required.')], format='%Y-%m-%d', default=date.today)
    remarks = TextAreaField('Remarks', validators=[Optional()])
