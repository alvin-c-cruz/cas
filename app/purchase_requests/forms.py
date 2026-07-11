"""Form for Purchase Request -- a thin requisition (mirror QuotationForm, minus pricing)."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField
from wtforms.validators import DataRequired, Optional
from app.utils.concurrency import RowVersionFormMixin


class PurchaseRequestForm(RowVersionFormMixin, FlaskForm):
    request_date = DateField('Request Date', validators=[
        DataRequired(message='Request date is required.')], format='%Y-%m-%d', default=date.today)
    reason = TextAreaField('Reason / Justification', validators=[Optional()])
