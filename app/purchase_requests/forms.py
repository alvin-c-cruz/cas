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
    # Optional and deliberately NOT checked against request_date -- owner
    # directive, matching PurchaseOrder.expected_date. A requestor who does not
    # yet know when the goods are wanted must still be able to raise the
    # requisition.
    date_needed = DateField('Date Needed', validators=[Optional()], format='%Y-%m-%d')
    reason = TextAreaField('Reason / Justification', validators=[Optional()])


class PurchaseRequestAmendForm(PurchaseRequestForm):
    """The PR form plus the reason a post-approval amendment must record.

    Mirrors PurchaseOrderAmendForm's rule (>=10 chars, matching cancel's). The
    inherited pr_number field is deliberately kept -- the amend template renders
    it readonly and the route never reassigns it, so the value round-trips for
    display without becoming editable.
    """
    amend_reason = TextAreaField('Reason for amendment', validators=[
        DataRequired(message='Please provide a reason for this amendment.'),
        Length(min=10, message='Please provide a reason (at least 10 characters).')])
