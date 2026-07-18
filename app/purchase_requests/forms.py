"""Form for Purchase Request -- a thin requisition (mirror QuotationForm, minus pricing)."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField, StringField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin


class PurchaseRequestForm(RowVersionFormMixin, FlaskForm):
    pr_number = StringField('PR #', validators=[
        DataRequired(message='PR number is required.'), Length(max=50)])
    request_date = DateField('Request Date', validators=[
        DataRequired(message='Request date is required.')], format='%Y-%m-%d', default=date.today)
    reason = TextAreaField('Reason / Justification', validators=[Optional()])
